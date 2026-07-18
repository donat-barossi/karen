"""Skill: timer e sveglie (delegati a Home Assistant)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .base import BaseSkill

log = logging.getLogger(__name__)


def _fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} secondi"
    elif seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m} minut{'o' if m == 1 else 'i'}" + (f" e {s} secondi" if s else "")
    else:
        h, rem = divmod(seconds, 3600)
        m = rem // 60
        return f"{h} or{'a' if h == 1 else 'e'}" + (f" e {m} minuti" if m else "")


class TimerSkill(BaseSkill):

    @property
    def handled_intents(self) -> list[str]:
        return ["timer", "alarm"]

    async def execute(self, intent_data: dict[str, Any]) -> str:
        intent = intent_data.get("intent")
        params = intent_data.get("parameters", {})
        ha_cfg = self._cfg.get("ha", {})

        if intent == "timer":
            duration_s = int(params.get("duration_s", params.get("duration", 60)))
            ok = await self._ha_call(
                ha_cfg,
                "timer.start",
                entity_id="timer.karen",
                duration=str(duration_s),
            )
            label = _fmt_duration(duration_s)
            if ok:
                return f"Timer di {label} avviato!"
            else:
                # Fallback: timer in-process
                asyncio.ensure_future(self._local_timer(duration_s))
                return f"Timer di {label} avviato localmente."

        if intent == "alarm":
            hour   = int(params.get("hour", 7))
            minute = int(params.get("minute", 0))
            ok = await self._ha_call(
                ha_cfg,
                "input_datetime.set_datetime",
                entity_id="input_datetime.karen_alarm",
                time=f"{hour:02d}:{minute:02d}:00",
            )
            if ok:
                return f"Sveglia impostata per le {hour}:{minute:02d}!"
            else:
                return f"Non riesco a impostare la sveglia. Riprova."

        return intent_data.get("response_it", "Comando non riconosciuto.")

    @staticmethod
    async def _ha_call(ha_cfg: dict, service: str, **data: Any) -> bool:
        domain, svc = service.split(".", 1)
        url = f"{ha_cfg.get('url', '')}/api/services/{domain}/{svc}"
        headers = {
            "Authorization": f"Bearer {ha_cfg.get('token', '')}",
            "Content-Type": "application/json",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=data, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=ha_cfg.get("timeout_s", 5)),
                ) as resp:
                    return resp.status in (200, 201)
        except Exception as e:
            log.warning("HA call fallita (%s): %s", service, e)
            return False

    @staticmethod
    async def _local_timer(seconds: int) -> None:
        """Timer locale senza HA – solo log (nessuna notifica vocale)."""
        log.info("Timer locale avviato: %d s", seconds)
        await asyncio.sleep(seconds)
        log.info("Timer scaduto! (%d s)", seconds)
