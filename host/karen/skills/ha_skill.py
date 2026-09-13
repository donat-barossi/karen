"""
Skill: controllo Home Assistant (luci, prese, interruttori, script, scene).
"""

from __future__ import annotations

import logging
from typing import Any

from ..ha_client import HomeAssistantClient, ha_action_error
from .base import BaseSkill

log = logging.getLogger(__name__)


class HomeAssistantSkill(BaseSkill):

    @property
    def handled_intents(self) -> list[str]:
        return ["ha_action", "recipe", "general"]

    async def execute(self, intent_data: dict[str, Any]) -> str:
        intent = intent_data.get("intent")

        # recipe e general: restituisce direttamente la risposta del LLM
        if intent in ("recipe", "general"):
            response = intent_data.get("response_it", "")
            if response and "[SKILL_WILL_FILL]" not in response:
                return response
            return "Non ho una risposta per questa domanda."

        # ha_action
        ha_cfg = self._cfg.get("ha", {})
        service  = intent_data.get("ha_service")
        entity   = intent_data.get("ha_entity")
        params   = intent_data.get("parameters", {})
        response = intent_data.get("response_it", "")

        if not service:
            return response or "Non so quale azione eseguire."

        data: dict[str, Any] = {}
        if entity:
            data["entity_id"] = entity

        # Parametri extra (es. brightness, color_temp)
        for key in ("brightness", "color_temp", "rgb_color", "temperature"):
            if key in params:
                data[key] = params[key]

        ha = HomeAssistantClient(ha_cfg)
        result = await ha.call_service(service, **data)
        if result.ok:
            return response or "Fatto!"
        return ha_action_error("eseguire il comando", result)
