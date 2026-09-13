"""Skill: data e ora corrente."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .base import BaseSkill

GIORNI_IT = ["lunedì", "martedì", "mercoledì", "giovedì",
             "venerdì", "sabato", "domenica"]
MESI_IT   = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
             "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def _format_spoken_time(hour: int, minute: int) -> str:
    """Testo adatto al TTS: evita ':' e ' e ' tra cifre (pause lunghe in Piper)."""
    if minute == 0:
        return f"Sono le {hour} in punto."
    if minute == 30:
        return f"Sono le {hour} e mezza."
    if minute == 15:
        return f"Sono le {hour} e un quarto."
    if minute == 45:
        return f"Sono le {hour} e tre quarti."
    if minute < 10:
        return f"Sono le {hour}, zero {minute}."
    return f"Sono le {hour},{minute:02d}."


class DateTimeSkill(BaseSkill):

    @property
    def handled_intents(self) -> list[str]:
        return ["time", "date"]

    def _now(self) -> datetime:
        tz_name = self._cfg.get("ha", {}).get("timezone", "Europe/Rome")
        return datetime.now(ZoneInfo(tz_name))

    async def execute(self, intent_data: dict[str, Any]) -> str:
        now = self._now()
        intent = intent_data.get("intent")

        if intent == "time":
            return _format_spoken_time(now.hour, now.minute)

        if intent == "date":
            giorno = GIORNI_IT[now.weekday()]
            mese   = MESI_IT[now.month - 1]
            return f"Oggi è {giorno} {now.day} {mese} {now.year}."

        return "Non so la data o l'ora corrente."
