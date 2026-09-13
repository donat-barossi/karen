"""Utility testo per sveglie/timer (senza dipendenze HA)."""

from __future__ import annotations

import re

WEEKDAY_IT = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
DEFAULT_ALARM_NAME = "Sveglia"
_AUTO_ALARM_NAME_RE = re.compile(r"^sveglia-\d+$", re.I)

DAY_ALIASES: dict[str, int] = {
    "lun": 0, "lunedì": 0, "lunedi": 0,
    "mar": 1, "martedì": 1, "martedi": 1,
    "mer": 2, "mercoledì": 2, "mercoledi": 2,
    "gio": 3, "giovedì": 3, "giovedi": 3,
    "ven": 4, "venerdì": 4, "venerdi": 4,
    "sab": 5, "sabato": 5,
    "dom": 6, "domenica": 6,
}


def parse_weekdays(text: str) -> list[int] | None:
    t = text.lower()
    found: set[int] = set()
    for key, wd in DAY_ALIASES.items():
        if key in t:
            found.add(wd)
    if "feriali" in t:
        found.update({0, 1, 2, 3, 4})
    if "weekend" in t or "fine settimana" in t:
        found.update({5, 6})
    if "tutti i giorni" in t or "ogni giorno" in t:
        return list(range(7))
    return sorted(found) if found else None


def fmt_duration(seconds: int) -> str:
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


def fmt_days(days: list[int]) -> str:
    if not days:
        return "una volta"
    return ", ".join(WEEKDAY_IT[d] for d in sorted(days))


def alarm_spoken_label(name: str) -> str | None:
    if not name or name == DEFAULT_ALARM_NAME or _AUTO_ALARM_NAME_RE.match(name):
        return None
    return name
