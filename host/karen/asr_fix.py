"""Correzioni ASR comuni (Whisper) prima del parsing intent."""

from __future__ import annotations

import re

# Typo frequenti su "sveglia" / "sveglie"
_SVEGLIA_TYPOS = (
    (re.compile(r"\bspeglia\b", re.I), "sveglia"),
    (re.compile(r"\bspelgia\b", re.I), "sveglia"),
    (re.compile(r"\bspeglie\b", re.I), "sveglie"),
    (re.compile(r"\bspelgie\b", re.I), "sveglie"),
)

# Musica / riproduci
_MUSIC_TYPOS = (
    (re.compile(r"\bvi produci\b", re.I), "riproduci"),
    (re.compile(r"\bri produci\b", re.I), "riproduci"),
    (re.compile(r"\bmi produci\b", re.I), "riproduci"),
    (re.compile(r"\briproduci\b", re.I), "riproduci"),
)

# Timer / imposta
_SETUP_TYPOS = (
    (re.compile(r"\bin posta\b", re.I), "imposta"),
    (re.compile(r"\bim posta\b", re.I), "imposta"),
    (re.compile(r"\bimpost\b", re.I), "imposta"),
)

# "rimuovi tutte le sveglie" → rimovi / vi muovi
_CANCEL_TYPOS = (
    (re.compile(r"\bvi muov\w*\b", re.I), "rimuovi"),
    (re.compile(r"\brimov\w*\b", re.I), "rimuovi"),
    (re.compile(r"\brimuov\w*\b", re.I), "rimuovi"),
    (re.compile(r"\bannull\w*\b", re.I), "annulla"),
    (re.compile(r"\bcancell\w*\b", re.I), "cancella"),
    (re.compile(r"\belimin\w*\b", re.I), "elimina"),
)

# "che ore sono" (Whisper spesso trascribe male)
_TIME_TYPOS = (
    (re.compile(r"\bchi o ne sono\b", re.I), "che ore sono"),
    (re.compile(r"\bchi ore sono\b", re.I), "che ore sono"),
    (re.compile(r"\bche orisuno\b", re.I), "che ore sono"),
    (re.compile(r"\bche orizzono\b", re.I), "che ore sono"),
    (re.compile(r"\bche or\w*sono\b", re.I), "che ore sono"),
    (re.compile(r"\borisuno\b", re.I), "ore sono"),
    (re.compile(r"\borizzono\b", re.I), "ore sono"),
    (re.compile(r"\bche ore son\b", re.I), "che ore sono"),
    (re.compile(r"\bch ore sono\b", re.I), "che ore sono"),
    (re.compile(r"\bche ora son\b", re.I), "che ora sono"),
    (re.compile(r"\bora son\b", re.I), "ora sono"),
    (re.compile(r"\bora e\b", re.I), "ora è"),
)

# Normalizza "12 e 15" → coerente per parser ora
_TIME_SEP = re.compile(
    r"\b(\d{1,2})\s+e\s+(\d{1,2})\b",
    re.I,
)


def fix_asr_transcript(text: str) -> str:
    """Normalizza errori ASR ricorrenti su comandi vocali in italiano."""
    t = text.strip()
    if not t:
        return t

    for pattern, repl in _MUSIC_TYPOS + _SETUP_TYPOS + _SVEGLIA_TYPOS + _TIME_TYPOS:
        t = pattern.sub(repl, t)

    if re.search(r"\bsvegl", t, re.I):
        for pattern, repl in _CANCEL_TYPOS:
            t = pattern.sub(repl, t)

    t = _TIME_SEP.sub(r"\1:\2", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t
