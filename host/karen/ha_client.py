"""Client REST per Home Assistant."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

log = logging.getLogger(__name__)


class HomeAssistantClient:
    def __init__(self, ha_cfg: dict) -> None:
        self._url = ha_cfg.get("url", "").rstrip("/")
        self._token = ha_cfg.get("token", "")
        self._timeout = aiohttp.ClientTimeout(total=ha_cfg.get("timeout_s", 5))
        self.timezone = ZoneInfo(ha_cfg.get("timezone", "Europe/Rome"))

    @property
    def configured(self) -> bool:
        return bool(self._url and self._token and "YOUR_HA" not in self._token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def call_service(self, service: str, **data: Any) -> bool:
        if not self.configured:
            log.warning("HA non configurato (url/token mancanti)")
            return False

        domain, svc = service.split(".", 1)
        url = f"{self._url}/api/services/{domain}/{svc}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=data, headers=self._headers(), timeout=self._timeout
                ) as resp:
                    if resp.status not in (200, 201):
                        body = await resp.text()
                        log.warning("HA %s → %d: %s", service, resp.status, body[:200])
                        return False
                    return True
        except aiohttp.ClientConnectorError:
            log.warning("HA non raggiungibile su %s", self._url)
            return False
        except Exception as e:
            log.exception("HA call errore (%s): %s", service, e)
            return False

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        if not self.configured:
            return None
        url = f"{self._url}/api/states/{entity_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, headers=self._headers(), timeout=self._timeout
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
    ) -> list[dict[str, Any]]:
        if not self.configured:
            return []

        url = f"{self._url}/api/services/calendar/get_events"
        payload = {
            "entity_id": entity_id,
            "start_date_time": start.isoformat(),
            "end_date_time": end.isoformat(),
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, headers=self._headers(), timeout=self._timeout
                ) as resp:
                    if resp.status not in (200, 201):
                        body = await resp.text()
                        log.warning("HA calendar.get_events → %d: %s", resp.status, body[:200])
                        return []
                    data = await resp.json()
                    if isinstance(data, dict):
                        return data.get(entity_id, {}).get("events", [])
                    if isinstance(data, list):
                        return data
                    return []
        except Exception as e:
            log.warning("HA calendar.get_events fallito: %s", e)
            return []

    async def create_calendar_event(
        self,
        entity_id: str,
        summary: str,
        start: datetime,
        end: datetime,
        description: str = "",
    ) -> bool:
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
