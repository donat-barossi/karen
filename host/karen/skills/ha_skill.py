"""
Skill: controllo Home Assistant (luci, prese, interruttori, script, scene).
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

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

        ok = await self._call_service(ha_cfg, service, data)
        if ok:
            return response or "Fatto!"
        else:
            return "Non riesco a comunicare con Home Assistant. Controlla la connessione."

    @staticmethod
    async def _call_service(ha_cfg: dict, service: str, data: dict) -> bool:
        domain, svc = service.split(".", 1)
        url = f"{ha_cfg.get('url', '')}/api/services/{domain}/{svc}"
        headers = {
            "Authorization": f"Bearer {ha_cfg.get('token', '')}",
            "Content-Type": "application/json",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=data, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=ha_cfg.get("timeout_s", 5)),
                ) as resp:
                    if resp.status not in (200, 201):
                        body = await resp.text()
                        log.warning("HA %s → %d: %s", service, resp.status, body[:200])
                        return False
                    return True
        except aiohttp.ClientConnectorError:
            log.warning("HA non raggiungibile su %s", ha_cfg.get("url"))
            return False
        except Exception as e:
            log.exception("HA call errore: %s", e)
            return False
