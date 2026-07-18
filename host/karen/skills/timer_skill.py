"""Skill: timer multipli e sveglie ricorrenti."""

from __future__ import annotations

import logging
import re
from typing import Any

from ..scheduling.service import ScheduleService, fmt_days, fmt_duration, parse_weekdays
from .base import BaseSkill

log = logging.getLogger(__name__)

ITALIAN_NUMBERS: dict[str, int] = {
    "un": 1, "una": 1, "uno": 1,
    "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
    "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
    "undici": 11, "dodici": 12, "quindici": 15, "venti": 20,
    "trenta": 30, "quaranta": 40, "cinquanta": 50, "sessanta": 60,
}

_NUM_WORD = (
    r"\d+|un[ao]?|due|tre|quattro|cinque|sei|sette|otto|nove|dieci|"
    r"undici|dodici|quindici|venti|trenta|quaranta|cinquanta|sessanta"
)


def _italian_number(token: str) -> int | None:
    token = token.lower().strip()
    if token.isdigit():
        return int(token)
    return ITALIAN_NUMBERS.get(token)


class TimerSkill(BaseSkill):

    def __init__(self, cfg: dict) -> None:
        super().__init__(cfg)
        self._sched: ScheduleService | None = cfg.get("schedule_service")

    @property
    def handled_intents(self) -> list[str]:
        return ["timer", "alarm", "ringing"]

    def _sched_svc(self) -> ScheduleService:
        if self._sched is None:
            raise RuntimeError("ScheduleService non inizializzato")
        return self._sched

    async def execute(self, intent_data: dict[str, Any]) -> str:
        intent = intent_data.get("intent")
        params = intent_data.get("parameters", {})

        if intent == "ringing":
            ring = self._cfg.get("ring_controller")
            if ring and params.get("action") == "dismiss":
                await ring.dismiss()
                return "Ok!"
            return "Non c'è nessun allarme attivo."

        sched = self._sched_svc()

        if intent == "timer":
            action = params.get("action", "start")

            if action in ("list", "status"):
                return sched.describe_timers()

            if action == "cancel":
                n = sched.cancel_timers(
                    name=params.get("name", ""),
                    timer_id=params.get("timer_id", ""),
                    cancel_all=bool(params.get("all")),
                )
                if n == 0:
                    return "Non ho trovato timer da annullare."
                if n == 1:
                    return "Timer annullato."
                return f"{n} timer annullati."

            duration_s = int(params.get("duration_s", params.get("duration", 60)))
            name = params.get("name", "")
            sched.start_timer(duration_s, name=name)
            label = fmt_duration(duration_s)
            return f"Ok, {label} a partire da adesso."

        if intent == "alarm":
            action = params.get("action", "set")

            if action in ("list", "status", "query"):
                return sched.describe_alarms()

            if action in ("skip_tomorrow", "skip"):
                n = sched.skip_tomorrow(params.get("alarm_id", ""))
                if n == 0:
                    return "Domani non hai sveglie programmate da saltare."
                if n == 1:
                    return "Ok, domani non suonerà la sveglia. La ricorrenza resta attiva."
                return f"Ok, domani non suoneranno {n} sveglie. Le ricorrenze restano attive."

            if action == "skip_next":
                n = sched.skip_next(params.get("alarm_id", ""))
                if n == 0:
                    return "Non ho sveglie da saltare."
                return "Ok, salto la prossima occorrenza. La ricorrenza resta attiva."

            if action in ("cancel", "disable"):
                ok = sched.disable_alarm(
                    alarm_id=params.get("alarm_id", ""),
                    name=params.get("name", ""),
                )
                return "Sveglia disattivata." if ok else "Non ho trovato la sveglia."

            hour = int(params.get("hour", 7))
            minute = int(params.get("minute", 0))
            days = params.get("days")
            if isinstance(days, list) and days:
                day_list = [int(d) for d in days]
            else:
                day_list = list(range(7))

            alarm = sched.upsert_alarm(
                hour, minute, day_list,
                name=params.get("name", ""),
                alarm_id=params.get("alarm_id", ""),
            )
            when = f"{hour:02d}:{minute:02d}"
            return (
                f"Sveglia {alarm['name']} impostata per le {when}, "
                f"{fmt_days(day_list)}."
            )

        return intent_data.get("response_it", "Comando non riconosciuto.")


def parse_timer_duration(text: str) -> int | None:
    t = text.lower()
    if "sveglia" in t and "timer" not in t:
        return None
    if not any(w in t for w in ("timer", "minut", "second", "or")):
        return None

    m = re.search(rf"({_NUM_WORD})\s*(?:minut[oi]|minutes?|min\b)", t)
    if m:
        n = _italian_number(m.group(1))
        if n is not None:
            return n * 60
    m = re.search(rf"({_NUM_WORD})\s*(?:second[oi]|sec\b)", t)
    if m:
        n = _italian_number(m.group(1))
        if n is not None:
            return n
    m = re.search(rf"({_NUM_WORD})\s*(?:or[ae]|h\b)", t)
    if m:
        n = _italian_number(m.group(1))
        if n is not None:
            return n * 3600
    return None


def parse_alarm_time(text: str) -> tuple[int, int] | None:
    t = text.lower()
    if not any(w in t for w in ("sveglia", "svegliami")):
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
        if w in t:
            return h, 0
    return None


def parse_alarm_intent(text: str) -> dict[str, Any] | None:
    t = text.lower()
    if any(p in t for p in ("domani non suonare", "non suonare domani", "salta domani", "salta la sveglia domani")):
        return {"intent": "alarm", "parameters": {"action": "skip_tomorrow"}}

    if any(p in t for p in ("salta prossima", "prossima sveglia", "salta la prossima")):
        return {"intent": "alarm", "parameters": {"action": "skip_next"}}

    if any(p in t for p in ("quali sveglie", "mostra sveglie", "sveglie attive")):
        return {"intent": "alarm", "parameters": {"action": "list"}}

    time = parse_alarm_time(t)
    if time is None:
        return None
    hour, minute = time
    days = parse_weekdays(t) or list(range(7))
    name = ""
    if "lavoro" in t or "feriali" in t:
        name = "feriali"
    elif days == [0, 2, 4]:
        name = "lun-mer-ven"
    elif days == [1, 3]:
        name = "mar-gio"
    return {
        "intent": "alarm",
        "parameters": {"action": "set", "hour": hour, "minute": minute, "days": days, "name": name},
    }


def parse_timer_intent(text: str) -> dict[str, Any] | None:
    t = text.lower()
    if any(p in t for p in ("annulla timer", "cancella timer", "ferma timer", "stop timer")):
        cancel_all = "tutti" in t
        return {"intent": "timer", "parameters": {"action": "cancel", "all": cancel_all}}

    if any(p in t for p in ("quali timer", "timer attivi", "mostra timer")):
        return {"intent": "timer", "parameters": {"action": "list"}}

    duration = parse_timer_duration(t)
    if duration is None:
        return None
    name = ""
    if "pasta" in t:
        name = "pasta"
    return {"intent": "timer", "parameters": {"action": "start", "duration_s": duration, "name": name}}
