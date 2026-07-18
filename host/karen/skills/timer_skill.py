"""Skill: timer e sveglie (delegati a Home Assistant)."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from ..ha_client import HomeAssistantClient
from .base import BaseSkill

log = logging.getLogger(__name__)


def _fmt_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} secondi"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        out = f"{m} minut{'o' if m == 1 else 'i'}"
        return out + (f" e {s} secondi" if s else "")
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    out = f"{h} or{'a' if h == 1 else 'e'}"
    return out + (f" e {m} minuti" if m else "")


def _duration_hms(seconds: int) -> str:
    h, rem = divmod(max(1, seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class TimerSkill(BaseSkill):

    @property
    def handled_intents(self) -> list[str]:
        return ["timer", "alarm"]

    async def execute(self, intent_data: dict[str, Any]) -> str:
        intent = intent_data.get("intent")
        params = intent_data.get("parameters", {})
        ha_cfg = self._cfg.get("ha", {})
        ha = HomeAssistantClient(ha_cfg)
        entities = ha_cfg.get("entities", {})
        timer_entity = entities.get("timer", "timer.karen")
        alarm_entity = entities.get("alarm", "input_datetime.karen_alarm")
        active_entity = entities.get("active", "input_boolean.karen_active")

        if intent == "timer":
            action = params.get("action", "start")
            if action == "cancel":
                ok = await ha.call_service("timer.cancel", entity_id=timer_entity)
                return "Timer annullato." if ok else "Non riesco ad annullare il timer."

            if action == "status":
                state = await ha.get_state(timer_entity)
                if not state:
                    return "Non riesco a leggere lo stato del timer."
                attrs = state.get("attributes", {})
                remaining = attrs.get("remaining", state.get("state", ""))
                if remaining in ("0", "idle", "unknown", "unavailable"):
                    return "Non c'è nessun timer attivo."
                return f"Il timer ha ancora {remaining}."

            duration_s = int(params.get("duration_s", params.get("duration", 60)))
            ok = await ha.call_service(
                "timer.start",
                entity_id=timer_entity,
                duration=_duration_hms(duration_s),
            )
            label = _fmt_duration(duration_s)
            if ok:
                return f"Timer di {label} avviato!"
            asyncio.ensure_future(self._local_timer(duration_s))
            return f"Timer di {label} avviato localmente."

        if intent == "alarm":
            action = params.get("action", "set")
            if action in ("status", "query"):
                state = await ha.get_state(alarm_entity)
                if not state:
                    return "Non riesco a leggere la sveglia."
                raw = state.get("state", "")
                if raw in ("unknown", "unavailable"):
                    return "La sveglia non è configurata."
                if "T" in raw:
                    raw = raw.split("T", 1)[1]
                parts = raw.split(":")
                if len(parts) >= 2:
                    return f"La sveglia è impostata per le {int(parts[0]):02d}:{int(parts[1]):02d}."
                return f"La sveglia è impostata per le {raw[:5]}."

            if action == "cancel":
                await ha.call_service(
                    "input_boolean.turn_off",
                    entity_id=active_entity,
                )
                return "Sveglia disattivata."

            hour = int(params.get("hour", 7))
            minute = int(params.get("minute", 0))
            ok = await ha.call_service(
                "input_datetime.set_datetime",
                entity_id=alarm_entity,
                time=f"{hour:02d}:{minute:02d}:00",
            )
            if ok:
                await ha.call_service("input_boolean.turn_on", entity_id=active_entity)
                return f"Sveglia impostata per le {hour:02d}:{minute:02d}!"
            return "Non riesco a impostare la sveglia. Controlla Home Assistant."

        return intent_data.get("response_it", "Comando non riconosciuto.")

    @staticmethod
    async def _local_timer(seconds: int) -> None:
        log.info("Timer locale avviato: %d s", seconds)
        await asyncio.sleep(seconds)
        log.info("Timer scaduto! (%d s)", seconds)


def parse_timer_duration(text: str) -> int | None:
    """Estrae durata timer da testo italiano (secondi)."""
    t = text.lower()
    if "timer" not in t and "sveglia" in t:
        return None

    m = re.search(r"(\d+)\s*(?:minut[oi]|min\b)", t)
    if m:
        return int(m.group(1)) * 60
    m = re.search(r"(\d+)\s*(?:second[oi]|sec\b)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*(?:or[ae]|h\b)", t)
    if m:
        return int(m.group(1)) * 3600
    return None


def parse_alarm_time(text: str) -> tuple[int, int] | None:
    """Estrae ora sveglia da testo italiano."""
    t = text.lower()
    if not any(w in t for w in ("sveglia", "alarm", "svegliami")):
        return None

    m = re.search(r"(\d{1,2})[:.](\d{2})", t)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = re.search(r"(\d{1,2})\s*(?:e mezza|e trenta)", t)
    if m:
        return int(m.group(1)), 30

    m = re.search(r"(?:alle|per le|ore)\s*(\d{1,2})(?:\s*(?:e\s*)?(\d{2}))?", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        return hour, minute

    words = {
        "una": 1, "uno": 1, "due": 2, "tre": 3, "quattro": 4,
        "cinque": 5, "sei": 6, "sette": 7, "otto": 8, "nove": 9,
        "dieci": 10, "undici": 11, "dodici": 12,
    }
    for w, h in words.items():
        if w in t and ("sveglia" in t or "svegliami" in t):
            return h, 0
    return None
