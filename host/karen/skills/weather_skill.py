"""
Skill: meteo tramite Open-Meteo API (gratuita, nessuna API key).
Richiede connessione internet. In modalità offline risponde con messaggio di fallback.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp

from .base import BaseSkill

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

WMO_CODES: dict[int, str] = {
    0: "cielo sereno",
    1: "prevalentemente sereno",
    2: "parzialmente nuvoloso",
    3: "nuvoloso",
    45: "nebbia",
    48: "nebbia con brina",
    51: "pioggerella leggera",
    53: "pioggerella moderata",
    55: "pioggerella intensa",
    61: "pioggia leggera",
    63: "pioggia moderata",
    65: "pioggia intensa",
    71: "neve leggera",
    73: "neve moderata",
    75: "neve intensa",
    80: "rovesci leggeri",
    81: "rovesci moderati",
    82: "rovesci intensi",
    95: "temporale",
    96: "temporale con grandine",
    99: "temporale con grandine intensa",
}


class WeatherSkill(BaseSkill):

    @property
    def handled_intents(self) -> list[str]:
        return ["weather"]

    async def execute(self, intent_data: dict[str, Any]) -> str:
        cfg = self._cfg.get("weather", {})
        lat  = cfg.get("latitude", 45.4654)
        lon  = cfg.get("longitude", 9.1859)
        when = intent_data.get("parameters", {}).get("when", "today")

        try:
            data = await self._fetch(lat, lon)
        except Exception as e:
            log.warning("Meteo non disponibile: %s", e)
            if cfg.get("offline_fallback", True):
                return ("Non riesco ad accedere alle previsioni meteo in questo momento. "
                        "Controlla la connessione internet.")
            return "Previsioni meteo non disponibili."

        return self._format_response(data, when)

    @staticmethod
    async def _fetch(lat: float, lon: float) -> dict:
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": ["weathercode", "temperature_2m_max", "temperature_2m_min",
                      "precipitation_sum"],
            "current_weather": "true",
            "timezone": "auto",
            "forecast_days": 3,
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(
                OPEN_METEO_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    @staticmethod
    def _format_response(data: dict, when: str) -> str:
        daily = data.get("daily", {})
        dates    = daily.get("time", [])
        codes    = daily.get("weathercode", [])
        max_t    = daily.get("temperature_2m_max", [])
        min_t    = daily.get("temperature_2m_min", [])

        if not dates:
            return "Non ho dati meteo disponibili."

        idx = 0  # oggi
        if when in ("tomorrow", "domani"):
            idx = 1
        elif when in ("after tomorrow", "dopodomani"):
            idx = 2

        if idx >= len(dates):
            idx = 0

        code = codes[idx] if idx < len(codes) else 0
        desc = WMO_CODES.get(code, "condizioni variabili")
        t_max = max_t[idx] if idx < len(max_t) else "?"
        t_min = min_t[idx] if idx < len(min_t) else "?"

        day_label = "Oggi" if idx == 0 else ("Domani" if idx == 1 else "Dopodomani")
        return (f"{day_label} le previsioni indicano {desc}, "
                f"con temperature tra {t_min}° e {t_max}°C.")
