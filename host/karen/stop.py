"""Riconoscimento comando globale STOP (allarme, timer, musica)."""

from __future__ import annotations

import re

from .scheduling.ringing import is_dismiss_phrase, normalize_dismiss_text

_MUSIC_STOP_PATTERNS = (
    re.compile(r"(?:ferma|stop|spegni|chiudi)musica"),
    re.compile(r"\b(?:ferma|fermate|stop|spegni|chiudi)\b.*\bmusica\b"),
    re.compile(r"\bmusica\b.*\b(?:ferma|fermate|stop|spegni|chiudi)\b"),
)


def is_music_stop_phrase(text: str) -> bool:
    t = normalize_dismiss_text(text)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return any(p.search(t) for p in _MUSIC_STOP_PATTERNS)


def is_global_stop_phrase(text: str) -> bool:
    """True se l'utente vuole fermare ciò che sta suonando adesso."""
    if is_dismiss_phrase(text):
        return True
    return is_music_stop_phrase(text)
