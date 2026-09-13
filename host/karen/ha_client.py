"""Client REST per Home Assistant."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

log = logging.getLogger(__name__)

HA_ERROR_NOT_CONFIGURED = "not_configured"
HA_ERROR_UNREACHABLE = "unreachable"
HA_ERROR_TIMEOUT = "timeout"
HA_ERROR_HTTP = "http"

HA_ERROR_MESSAGES: dict[str, str] = {
    HA_ERROR_NOT_CONFIGURED: "Home Assistant non è configurato.",
    HA_ERROR_UNREACHABLE: (
        "Non riesco a contattare Home Assistant. "
        "Verifica che sia acceso e connesso in rete."
    ),
    HA_ERROR_TIMEOUT: "Home Assistant non risponde in tempo. Riprova tra poco.",
    HA_ERROR_HTTP: "Home Assistant ha restituito un errore.",
}


@dataclass(frozen=True)
class HaCallResult:
    ok: bool
    error: str | None = None

    @staticmethod
    def success() -> HaCallResult:
        return HaCallResult(True)

    @staticmethod
    def failure(error: str) -> HaCallResult:
        return HaCallResult(False, error)

    @property
    def user_message(self) -> str:
        if self.ok:
            return ""
        return HA_ERROR_MESSAGES.get(self.error or HA_ERROR_UNREACHABLE, HA_ERROR_MESSAGES[HA_ERROR_UNREACHABLE])


def ha_action_error(action: str, result: HaCallResult) -> str:
    """Messaggio TTS quando un'azione su HA fallisce."""
    if result.ok:
        return ""
    detail = result.user_message
    return f"Non riesco a {action}. {detail}"


class HomeAssistantClient:
    def __init__(self, ha_cfg: dict) -> None:
        self._url = ha_cfg.get("url", "").rstrip("/")
        self._token = ha_cfg.get("token", "")
        self._timeout_s = float(ha_cfg.get("timeout_s", 5))
        self.timezone = ZoneInfo(ha_cfg.get("timezone", "Europe/Rome"))

    @property
    def configured(self) -> bool:
        return bool(self._url and self._token and "YOUR_HA" not in self._token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def call_service(
        self,
        service: str,
        *,
        timeout_s: float | None = None,
        **data: Any,
    ) -> HaCallResult:
        if not self.configured:
            log.warning("HA non configurato (url/token mancanti)")
            return HaCallResult.failure(HA_ERROR_NOT_CONFIGURED)

        domain, svc = service.split(".", 1)
        url = f"{self._url}/api/services/{domain}/{svc}"
        timeout = aiohttp.ClientTimeout(total=timeout_s or self._timeout_s)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=data, headers=self._headers(), timeout=timeout
                ) as resp:
                    if resp.status not in (200, 201):
                        body = await resp.text()
                        log.warning("HA %s → %d: %s", service, resp.status, body[:200])
                        return HaCallResult.failure(HA_ERROR_HTTP)
                    return HaCallResult.success()
        except aiohttp.ClientConnectorError:
            log.warning("HA non raggiungibile su %s", self._url)
            return HaCallResult.failure(HA_ERROR_UNREACHABLE)
        except (asyncio.TimeoutError, TimeoutError, aiohttp.ServerTimeoutError):
            log.warning(
                "HA %s timeout (%.1fs)",
                service,
                timeout_s or self._timeout_s,
            )
            return HaCallResult.failure(HA_ERROR_TIMEOUT)
        except Exception as e:
            log.exception("HA call errore (%s): %s", service, e)
            return HaCallResult.failure(HA_ERROR_UNREACHABLE)

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        if not self.configured:
            return None
        url = f"{self._url}/api/states/{entity_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=self._timeout_s)
                ) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.json()
        except Exception as e:
            log.warning("HA get_state(%s) fallito: %s", entity_id, e)
            return None

    async def get_calendar_events(
        self,
        entity_id: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]] | None:
        if not self.configured:
            return None

        url = f"{self._url}/api/services/calendar/get_events"
        payload = {
            "entity_id": entity_id,
            "start_date_time": start.isoformat(),
            "end_date_time": end.isoformat(),
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers=self._headers(),
                    timeout=aiohttp.ClientTimeout(total=self._timeout_s),
                ) as resp:
                    if resp.status not in (200, 201):
                        body = await resp.text()
                        log.warning("HA calendar.get_events → %d: %s", resp.status, body[:200])
                        return None
                    data = await resp.json()
                    if isinstance(data, dict):
                        return data.get(entity_id, {}).get("events", [])
                    if isinstance(data, list):
                        return data
                    return []
        except aiohttp.ClientConnectorError:
            log.warning("HA non raggiungibile su %s", self._url)
            return None
        except (asyncio.TimeoutError, TimeoutError, aiohttp.ServerTimeoutError):
            log.warning("HA calendar.get_events timeout (%.1fs)", self._timeout_s)
            return None
        except Exception as e:
            log.warning("HA calendar.get_events fallito: %s", e)
            return None

    async def create_calendar_event(
        self,
        entity_id: str,
        summary: str,
        start: datetime,
        end: datetime,
        description: str = "",
    ) -> HaCallResult:
        return await self.call_service(
            "calendar.create_event",
            entity_id=entity_id,
            summary=summary,
            description=description,
            start_date_time=start.isoformat(),
            end_date_time=end.isoformat(),
        )

    def day_range(self, when: str) -> tuple[datetime, datetime]:
        now = datetime.now(self.timezone)
        if when in ("tomorrow", "domani"):
            day = (now + timedelta(days=1)).date()
        elif when in ("week", "settimana"):
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=7)
        else:
            day = now.date()

        start = datetime.combine(day, datetime.min.time(), tzinfo=self.timezone)
        end = start + timedelta(days=1) - timedelta(seconds=1)
        return start, end
