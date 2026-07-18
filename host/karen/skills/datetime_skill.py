"""Skill: data e ora corrente."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import BaseSkill

GIORNI_IT = ["lunedì", "martedì", "mercoledì", "giovedì",
             "venerdì", "sabato", "domenica"]
MESI_IT   = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
             "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]


class DateTimeSkill(BaseSkill):

    @property
    def handled_intents(self) -> list[str]:
        return ["time", "date"]

    async def execute(self, intent_data: dict[str, Any]) -> str:
        now = datetime.now()
        intent = intent_data.get("intent")

        if intent == "time":
            hour   = now.hour
            minute = now.minute
            if minute == 0:
                return f"Sono le {hour} in punto."
            elif minute == 30:
                return f"Sono le {hour} e mezza."
            elif minute < 10:
                return f"Sono le {hour} e {minute} minuti."
            else:
                return f"Sono le {hour}:{minute:02d}."

        if intent == "date":
            giorno = GIORNI_IT[now.weekday()]
            mese   = MESI_IT[now.month - 1]
            return f"Oggi è {giorno} {now.day} {mese} {now.year}."

        return "Non so la data o l'ora corrente."
