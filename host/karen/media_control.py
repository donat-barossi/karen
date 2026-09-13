"""Comandi vocali globali pausa / riprendi / ripeti (non durante allarmi)."""

from __future__ import annotations

import re

PAUSE_PHRASES = ("pausa", "aspetta", "sospendi")
RESUME_PHRASES = ("riprendi", "continua", "vai avanti")
REPEAT_PHRASES = ("ripeti", "non ho capito")
NEXT_PHRASES = (
    "next",
    "successivo",
    "prossimo",
    "prossima",
    "salta",
    "brano successivo",
    "canzone successiva",
    "canzone successivo",
)
PREVIOUS_PHRASES = (
    "previous",
    "precedente",
    "indietro",
    "brano precedente",
    "canzone precedente",
)

_SNOOZE_HINTS = (
    "postponi",
    "postpon",
    "piu tardi",
    "più tardi",
    "snooze",
    "rimanda",
    "rimand",
)
_NUM_WORD = (
    r"\d+|un[ao]?|due|tre|quattro|cinque|sei|sette|otto|nove|dieci|"
    r"undici|dodici|quindici|venti"
)
_ITALIAN_NUMBERS: dict[str, int] = {
    "un": 1, "una": 1, "uno": 1,
    "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
    "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10,
    "undici": 11, "dodici": 12, "quindici": 15, "venti": 20,
}


def normalize_voice_cmd(text: str) -> str:
    t = text.lower().strip()
    for wake in (
        "hey jarvis", "hi jarvis", "jarvis",
        "hey kira", "ehi kira", "hey karen", "ehi karen", "kira", "karen",
    ):
        t = t.replace(wake, " ")
    t = re.sub(r"[^\w\s']", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _normalize_cmd(text: str) -> str:
    return normalize_voice_cmd(text)


def _matches_phrase(t: str, phrases: tuple[str, ...]) -> bool:
    if not t:
        return False
    if t in phrases:
        return True
    for phrase in phrases:
        if " " in phrase and (t == phrase or t.startswith(phrase)):
            return True
    first = t.split()[0] if t.split() else ""
    return first in phrases


def is_global_pause_phrase(text: str) -> bool:
    return _matches_phrase(_normalize_cmd(text), PAUSE_PHRASES)


def is_global_resume_phrase(text: str) -> bool:
    return _matches_phrase(_normalize_cmd(text), RESUME_PHRASES)


def is_global_repeat_phrase(text: str) -> bool:
    return _matches_phrase(_normalize_cmd(text), REPEAT_PHRASES)


def is_global_next_phrase(text: str) -> bool:
    return _matches_phrase(_normalize_cmd(text), NEXT_PHRASES)


def is_global_previous_phrase(text: str) -> bool:
    return _matches_phrase(_normalize_cmd(text), PREVIOUS_PHRASES)


def parse_snooze_minutes(text: str) -> int | None:
    """Minuti di snooze sveglia; default 5 se riconosciuto senza durata."""
    t = _normalize_cmd(text)
    if not t:
        return None

    if re.search(rf"(?:dammi|ancora)\s+({_NUM_WORD})\s+minut", t):
        m = re.search(rf"(?:dammi|ancora)\s+({_NUM_WORD})\s+minut", t)
        if m:
            return _italian_number(m.group(1))

    m = re.search(rf"({_NUM_WORD})\s+minut", t)
    if m and any(h in t for h in _SNOOZE_HINTS + ("dammi", "ancora", "minut")):
        return _italian_number(m.group(1))

    if any(h in t for h in _SNOOZE_HINTS):
        return 5
    if re.search(r"dammi\s+un\s+po", t):
        return 5
    return None


def _italian_number(token: str) -> int:
    token = token.lower().strip()
    if token.isdigit():
        return max(1, int(token))
    return _ITALIAN_NUMBERS.get(token, 5)
