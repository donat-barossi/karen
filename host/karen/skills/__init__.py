"""Karen Skills – Registry e base class."""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseSkill
from .datetime_skill import DateTimeSkill
from .timer_skill import TimerSkill
from .weather_skill import WeatherSkill
from .ha_skill import HomeAssistantSkill

log = logging.getLogger(__name__)

FALLBACK_RESPONSE = "Non so rispondere a questa domanda al momento."


def _looks_english(text: str) -> bool:
    t = f" {text.lower()} "
    markers = (
        " the ", " you ", " i'm ", " i am ", " how can i ", " unable to ",
        " please ", " today?", " help you", " language model",
    )
    return any(m in t for m in markers)


class SkillRegistry:
    """
    Registra tutte le skill e smista l'intent al gestore corretto.
    """

    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg
        self._skills: dict[str, BaseSkill] = {}

    async def initialize(self) -> None:
        skills: list[BaseSkill] = [
            DateTimeSkill(self._cfg),
            TimerSkill(self._cfg),
            WeatherSkill(self._cfg),
            HomeAssistantSkill(self._cfg),
        ]
        for skill in skills:
            await skill.initialize()
            for intent in skill.handled_intents:
                self._skills[intent] = skill
            log.debug("Skill caricata: %s → %s", skill.__class__.__name__, skill.handled_intents)

    async def execute(self, intent_data: dict[str, Any]) -> str:
        """
        Esegue la skill appropriata e restituisce la risposta italiana.

        Args:
            intent_data: dizionario JSON dell'LLM

        Returns:
            Risposta in italiano da sintetizzare.
        """
        intent = intent_data.get("intent", "unknown")
        response_it = intent_data.get("response_it", "")

        if response_it and _looks_english(response_it):
            log.warning("Risposta LLM in inglese ignorata: %s", response_it[:80])
            response_it = ""
            intent_data = {**intent_data, "response_it": ""}

        # Se la skill ha già una risposta valida dal LLM, potrebbe usarla
        # ma la skill può sovrascrivere con dati freschi (es. ora esatta, meteo)

        skill = self._skills.get(intent)
        if skill:
            try:
                result = await skill.execute(intent_data)
                return result
            except Exception as e:
                log.exception("Errore skill '%s': %s", intent, e)
                return "Si è verificato un errore nell'esecuzione del comando."

        # Nessuna skill specifica: usa la risposta del LLM come fallback
        if response_it and "[SKILL_WILL_FILL]" not in response_it:
            return response_it

        return FALLBACK_RESPONSE

    async def shutdown(self) -> None:
        for skill in set(self._skills.values()):
            await skill.shutdown()
