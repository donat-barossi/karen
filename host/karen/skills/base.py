"""Karen Skills – Base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseSkill(ABC):
    """Classe base per tutte le skill di Karen."""

    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg

    @property
    @abstractmethod
    def handled_intents(self) -> list[str]:
        """Lista degli intent gestiti da questa skill."""
        ...

    async def initialize(self) -> None:
        """Inizializzazione asincrona (override se necessario)."""
        pass

    @abstractmethod
    async def execute(self, intent_data: dict[str, Any]) -> str:
        """
        Esegue l'azione e restituisce la risposta in italiano.

        Args:
            intent_data: dizionario con intent, parameters, response_it, ecc.

        Returns:
            Stringa da sintetizzare vocalmente.
        """
        ...

    async def shutdown(self) -> None:
        """Cleanup (override se necessario)."""
        pass
