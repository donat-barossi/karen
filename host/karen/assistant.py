"""Nome e messaggi dell'assistente vocale (configurabile)."""

from __future__ import annotations

from typing import Any


def assistant_name(cfg: dict[str, Any]) -> str:
    return str(cfg.get("assistant", {}).get("name", "Jarvis"))


def assistant_greeting(cfg: dict[str, Any]) -> str:
    custom = cfg.get("assistant", {}).get("greeting")
    if custom:
        return str(custom)
    return f"Ciao! Sono {assistant_name(cfg)}, come posso aiutarti?"
