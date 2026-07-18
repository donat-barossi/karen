"""Skill: calendario e promemoria (Outlook via Home Assistant)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from ..ha_client import HomeAssistantClient
from .base import BaseSkill

log = logging.getLogger(__name__)

_WEEKDAYS = (
    "lunedì", "martedì", "mercoledì", "giovedì",
    "venerdì", "sabato", "domenica",
)


class CalendarSkill(BaseSkill):

    @property
    def handled_intents(self) -> list[str]:
        return ["calendar_query", "calendar_create", "reminder"]

    async def execute(self, intent_data: dict[str, Any]) -> str:
        ha_cfg = self._cfg.get("ha", {})
        cal_cfg = ha_cfg.get("calendar", {})
        entity_id = cal_cfg.get("entity_id")
        ha = HomeAssistantClient(ha_cfg)

        if not entity_id:
            return (
                "Il calendario non è configurato. "
                "Collega Outlook in Home Assistant e imposta ha.calendar.entity_id."
            )

        intent = intent_data.get("intent")
        params = intent_data.get("parameters", {})

        if intent == "calendar_query":
            return await self._query_events(ha, entity_id, params)

        if intent in ("calendar_create", "reminder"):
            return await self._create_event(ha, entity_id, params, is_reminder=intent == "reminder")

        return intent_data.get("response_it", "Comando calendario non riconosciuto.")

    async def _query_events(
        self, ha: HomeAssistantClient, entity_id: str, params: dict[str, Any]
    ) -> str:
        when = params.get("when", "today")
        start, end = ha.day_range(when)
        events = await ha.get_calendar_events(entity_id, start, end)

        if not events:
            label = "oggi" if when in ("today", "oggi") else when
            return f"Non hai eventi in calendario per {label}."

        lines: list[str] = []
        for ev in events[:5]:
            title = ev.get("summary") or ev.get("title") or "Evento"
            start_raw = ev.get("start") or ev.get("start_time") or ""
            time_str = self._format_event_time(start_raw)
            lines.append(f"{time_str} {title}".strip())

        prefix = "Oggi" if when in ("today", "oggi") else "Domani" if when in ("tomorrow", "domani") else "In calendario"
        if len(events) > 5:
            return f"{prefix}: " + "; ".join(lines) + f"; e altri {len(events) - 5} eventi."
        return f"{prefix}: " + "; ".join(lines) + "."

    async def _create_event(
        self,
        ha: HomeAssistantClient,
        entity_id: str,
        params: dict[str, Any],
        *,
        is_reminder: bool,
    ) -> str:
        title = params.get("title") or params.get("summary") or "Promemoria Karen"
        start = self._parse_event_start(ha, params)
        duration_min = int(params.get("duration_min", 30 if not is_reminder else 15))
        end = start + timedelta(minutes=duration_min)

        ok = await ha.create_calendar_event(
            entity_id=entity_id,
            summary=title,
            start=start,
            end=end,
            description=params.get("description", "Creato da Karen"),
        )
        if not ok:
            return "Non riesco a salvare l'evento nel calendario."

        when = start.strftime("%d/%m alle %H:%M")
        if is_reminder:
            return f"Promemoria impostato: {title}, {when}."
        return f"Evento aggiunto al calendario: {title}, {when}."

    @staticmethod
    def _format_event_time(start_raw: str) -> str:
        if not start_raw:
            return ""
        if "T" in start_raw:
            try:
                dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
                if dt.hour == 0 and dt.minute == 0:
                    return _WEEKDAYS[dt.weekday()] if hasattr(dt, "weekday") else ""
                return f"alle {dt.hour:02d}:{dt.minute:02d}"
            except ValueError:
                pass
        return start_raw[:16]

    @staticmethod
    def _parse_event_start(ha: HomeAssistantClient, params: dict[str, Any]) -> datetime:
        now = datetime.now(ha.timezone)

        if params.get("datetime_iso"):
            return datetime.fromisoformat(str(params["datetime_iso"])).astimezone(ha.timezone)

        if params.get("date") and params.get("hour") is not None:
            day = datetime.strptime(str(params["date"]), "%Y-%m-%d").date()
            hour = int(params["hour"])
            minute = int(params.get("minute", 0))
            return datetime.combine(day, datetime.min.time(), tzinfo=ha.timezone).replace(
                hour=hour, minute=minute
            )

        when = params.get("when", "today")
        hour = int(params.get("hour", now.hour))
        minute = int(params.get("minute", 0))

        if when in ("tomorrow", "domani"):
            day = (now + timedelta(days=1)).date()
        else:
            day = now.date()

        start = datetime.combine(day, datetime.min.time(), tzinfo=ha.timezone).replace(
            hour=hour, minute=minute
        )
        if start <= now and when not in ("tomorrow", "domani"):
            start += timedelta(days=1)
        return start
