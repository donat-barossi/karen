"""Skill: timer multipli e sveglie ricorrenti."""

from __future__ import annotations

import logging
import re
from typing import Any

from ..asr_fix import fix_asr_transcript
from ..scheduling.text_utils import parse_weekdays
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

_ALARM_KW = re.compile(r"\b(?:svegl\w*|spegl\w*)\b", re.I)
_CANCEL_ALARM_RE = re.compile(
    r"\b(?:annulla|annull|cancella|disattiva|elimina|ferma|stop|togli|rimuovi)\b",
    re.I,
)
_TIME_INTRO = r"(?:alle|per le|ore|alle ore|a\s+)\s*"
_ITALIAN_HOUR_WORDS: dict[str, int] = {
    "una": 1, "uno": 1, "due": 2, "tre": 3, "quattro": 4,
    "cinque": 5, "sei": 6, "sette": 7, "otto": 8, "nove": 9,
    "dieci": 10, "undici": 11, "dodici": 12,
}
_HOUR_WORD_PAT = "|".join(sorted(_ITALIAN_HOUR_WORDS, key=len, reverse=True))
_ALARM_ECHO_RE = re.compile(
    r"\b(?:impostata|impostato|programmata|programmato|annullata|annullato)\b",
    re.I,
)


def _looks_like_alarm_echo(text: str) -> bool:
    """Ignora frasi di risposta TTS riascoltate dal microfono."""
    if _ALARM_ECHO_RE.search(text):
        return True
    return bool(re.search(r"\bsveglia-\d+\b", text, re.I))


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
        from ..scheduling.service import ScheduleService
        from ..scheduling.text_utils import alarm_spoken_label, fmt_days, fmt_duration

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

            if action == "next":
                return sched.describe_next_alarm()

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
                if params.get("all"):
                    n = sched.disable_all_alarms()
                    if n == 0:
                        return "Non hai sveglie attive."
                    if n == 1:
                        return "Sveglia disattivata."
                    return f"{n} sveglie disattivate."
                ok = sched.disable_alarm(
                    alarm_id=params.get("alarm_id", ""),
                    name=params.get("name", ""),
                )
                return "Sveglia disattivata." if ok else "Non ho trovato la sveglia."

            if "hour" not in params:
                return "A che ora vuoi la sveglia?"

            hour = int(params["hour"])
            minute = int(params.get("minute", 0))
            days = params.get("days")
            one_shot = bool(params.get("one_shot"))
            if isinstance(days, list) and days == list(range(7)) and not one_shot:
                if not params.get("recurring") and not params.get("every_day"):
                    one_shot = True
                    days = None

            if one_shot or not days:
                day_list = sched.one_shot_days(hour, minute)
                one_shot = True
            else:
                day_list = [int(d) for d in days]

            alarm = sched.upsert_alarm(
                hour, minute, day_list,
                name=params.get("name", ""),
                alarm_id=params.get("alarm_id", ""),
                one_shot=one_shot,
            )
            when = f"{hour:02d}:{minute:02d}"
            spoken = alarm_spoken_label(alarm.get("name", ""))
            if one_shot:
                label = sched.one_shot_label(hour, minute)
                if spoken:
                    return f"Sveglia {spoken} impostata per le {when} di {label}."
                return f"Sveglia impostata per le {when} di {label}."
            if spoken:
                return (
                    f"Sveglia {spoken} impostata per le {when}, "
                    f"{fmt_days(day_list)}."
                )
            return f"Sveglia impostata per le {when}, {fmt_days(day_list)}."

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
    t = fix_asr_transcript(text.lower())
    if not _ALARM_KW.search(t) or _looks_like_alarm_echo(t):
        return None

    if "mezzogiorno" in t:
        return 12, 0
    if "mezzanotte" in t:
        return 0, 0

    m = re.search(r"(\d{1,2})[:.](\d{2})", t)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = re.search(r"(\d{1,2})\s*(?:e mezza|e trenta)", t)
    if m:
        return int(m.group(1)), 30

    m = re.search(rf"{_TIME_INTRO}(\d{{1,2}})\s+(\d{{1,2}})\b", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute

    m = re.search(rf"{_TIME_INTRO}(\d{{1,2}})(?:\s*(?:e\s*)?(\d{{2}}))?", t)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        return hour, minute

    m = re.search(
        rf"{_TIME_INTRO}({_HOUR_WORD_PAT})(?:\s*(?:e\s*)?(quindici|trenta|(\d{{2}})))?",
        t,
    )
    if m:
        hour = _ITALIAN_HOUR_WORDS[m.group(1)]
        minute_raw = m.group(2) or m.group(3)
        if minute_raw in ("quindici", "trenta"):
            minute = 15 if minute_raw == "quindici" else 30
        elif minute_raw:
            minute = int(minute_raw)
        else:
            minute = 0
        return hour, minute

    return None


_ALARM_QUERY_RE = re.compile(
    r"\b(?:quali|qual\s*[eè]|che|quando|dimmi|mostra|elenco|lista|"
    r"qual\s*ora|a\s*che\s*ora|che\s*ora|quale)\b",
    re.I,
)
_SKIP_NEXT_RE = re.compile(
    r"\b(?:salta|annulla|disattiva|non\s+suonare|rimanda)\b.*\b(?:prossim[ao]|successiv[ao])\b|"
    r"\b(?:prossim[ao]|successiv[ao])\b.*\b(?:salta|annulla|non\s+suonare)\b|"
    r"\bsalta\s+(?:la\s+)?prossim",
    re.I,
)


def _parse_alarm_query_action(text: str) -> str | None:
    """Ritorna 'list', 'next' o None se non è una domanda sulle sveglie."""
    if not _ALARM_KW.search(text):
        return None
    if not _ALARM_QUERY_RE.search(text) and not re.search(
        r"\b(?:attive|impostate|programmate|ci\s+sono)\b", text
    ):
        if not re.search(r"\b(?:mie|mio|mia)\s+svegl", text):
            return None
    if re.search(r"\b(?:prossim[ao]|successiv[ao])\b", text):
        return "next"
    if re.search(r"\bsveglie\b", text):
        return "list"
    if re.search(r"\b(?:quali|elenco|lista|mostra|attive|impostate)\b", text):
        return "list"
    if re.search(r"\bmie?\s+svegl", text):
        return "list"
    return "next"


def parse_alarm_intent(text: str) -> dict[str, Any] | None:
    t = fix_asr_transcript(text.lower())
    if _looks_like_alarm_echo(t):
        return None

    query_action = _parse_alarm_query_action(t)
    if query_action:
        return {"intent": "alarm", "parameters": {"action": query_action}}

    if _ALARM_KW.search(t) and _CANCEL_ALARM_RE.search(t):
        cancel_all = bool(re.search(r"\b(?:tutte|tutti)\b", t))
        return {"intent": "alarm", "parameters": {"action": "cancel", "all": cancel_all}}

    if re.search(r"\b(?:tutte|tutti)\b", t) and re.search(r"\bsvegl", t) and re.search(
        r"\b(?:rimuovi|cancella|annulla|elimina|disattiva|togli)\b", t
    ):
        return {"intent": "alarm", "parameters": {"action": "cancel", "all": True}}

    if any(p in t for p in ("domani non suonare", "non suonare domani", "salta domani", "salta la sveglia domani")):
        return {"intent": "alarm", "parameters": {"action": "skip_tomorrow"}}

    if _SKIP_NEXT_RE.search(t):
        return {"intent": "alarm", "parameters": {"action": "skip_next"}}

    if any(p in t for p in (
        "quali sveglie", "mostra sveglie", "sveglie attive",
        "che sveglie", "che sveglia", "sveglie impostate", "sveglie ci sono",
        "le mie sveglie", "mie sveglie",
    )):
        return {"intent": "alarm", "parameters": {"action": "list"}}

    time = parse_alarm_time(t)
    if time is None:
        return None
    hour, minute = time
    days = parse_weekdays(t)
    name = ""
    if "lavoro" in t or "feriali" in t:
        name = "feriali"
    elif days == [0, 2, 4]:
        name = "lun-mer-ven"
    elif days == [1, 3]:
        name = "mar-gio"
    params: dict[str, Any] = {
        "action": "set",
        "hour": hour,
        "minute": minute,
        "name": name,
    }
    if days is not None:
        params["days"] = days
        if "tutti i giorni" in t or "ogni giorno" in t:
            params["every_day"] = True
    else:
        params["one_shot"] = True
    return {"intent": "alarm", "parameters": params}


def parse_timer_intent(text: str) -> dict[str, Any] | None:
    t = fix_asr_transcript(text.lower())
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
