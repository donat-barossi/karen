"""
Skill: meteo tramite Open-Meteo API (gratuita, nessuna API key).
Richiede connessione internet. In modalità offline risponde con messaggio di fallback.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..asr_fix import fix_asr_transcript
from .base import BaseSkill

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"

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

_WEATHER_TRIGGER = re.compile(
    r"\b(?:che\s+tempo|tempo\s+fa|tempo\s+far|previsioni|meteo|com(?:e|'?)?\s+far)\b",
    re.I,
)
_CITY_INTRO = re.compile(
    r"\b(?:a|per|in|su)\s+([a-zàèéìòù'`-]+(?:\s+[a-zàèéìòù'`-]+)*)",
    re.I,
)
_WHEN_NOISE = re.compile(
    r"\b(?:dopodomani|domani|oggi|"
    r"luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica|"
    r"lun|mar|mer|gio|ven|sab|dom)\b",
    re.I,
)

_WEEKDAY_MAP: dict[str, int] = {
    "lun": 0, "lunedì": 0, "lunedi": 0,
    "mar": 1, "martedì": 1, "martedi": 1,
    "mer": 2, "mercoledì": 2, "mercoledi": 2,
    "gio": 3, "giovedì": 3, "giovedi": 3,
    "ven": 4, "venerdì": 4, "venerdi": 4,
    "sab": 5, "sabato": 5,
    "dom": 6, "domenica": 6,
}


def parse_weather_intent(text: str) -> dict[str, Any] | None:
    """Riconosce richieste meteo con città e/o giorno opzionali."""
    t = fix_asr_transcript(text.lower()).strip()
    if not t or not _WEATHER_TRIGGER.search(t):
        return None

    params: dict[str, Any] = {"when": _parse_weather_when(t)}
    city = _parse_weather_city(t)
    if city:
        params["city"] = city

    return {"intent": "weather", "parameters": params}


def _parse_weather_when(text: str) -> str:
    if re.search(r"\bdopodomani\b", text):
        return "after_tomorrow"
    if re.search(r"\bdomani\b", text):
        return "tomorrow"
    if re.search(r"\boggi\b", text):
        return "today"
    for token, wd in _WEEKDAY_MAP.items():
        if re.search(rf"\b{re.escape(token)}\b", text):
            return f"weekday:{wd}"
    return "today"


def _parse_weather_city(text: str) -> str:
    m = _CITY_INTRO.search(text)
    if not m:
        return ""
    city = m.group(1).strip()
    city = _WHEN_NOISE.sub("", city).strip()
    city = re.sub(r"\s+(?:fa|farà|far[aà]|c(?:e|'?)?\s+)", " ", city, flags=re.I).strip()
    if len(city) < 2:
        return ""
    return city


class WeatherSkill(BaseSkill):

    @property
    def handled_intents(self) -> list[str]:
        return ["weather"]

    async def execute(self, intent_data: dict[str, Any]) -> str:
        cfg = self._cfg.get("weather", {})
        params = intent_data.get("parameters", {})
        when = params.get("when", "today")
        city_query = (params.get("city") or "").strip()

        tz_name = cfg.get("timezone", "Europe/Rome")
        tz = ZoneInfo(tz_name)

        try:
            if city_query:
                lat, lon, place = await self._geocode(city_query)
            else:
                lat = float(cfg.get("latitude", 41.6488))
                lon = float(cfg.get("longitude", -0.8891))
                place = cfg.get("default_city", "")
        except ValueError as e:
            return str(e)
        except Exception as e:
            log.warning("Geocoding fallito: %s", e)
            if cfg.get("offline_fallback", True):
                return ("Non riesco a trovare quella città o a collegarmi al servizio meteo.")
            return "Previsioni meteo non disponibili."

        try:
            data = await self._fetch(lat, lon, tz_name)
        except Exception as e:
            log.warning("Meteo non disponibile: %s", e)
            if cfg.get("offline_fallback", True):
                return ("Non riesco ad accedere alle previsioni meteo in questo momento. "
                        "Controlla la connessione internet.")
            return "Previsioni meteo non disponibili."

        return self._format_response(data, when, place, tz)

    @staticmethod
    async def _geocode(name: str) -> tuple[float, float, str]:
        import aiohttp

        params = {"name": name, "count": 5, "language": "it", "format": "json"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                GEOCODING_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        results = data.get("results") or []
        if not results:
            raise ValueError(f"Non ho trovato la città «{name}».")

        name_l = name.lower()
        best = results[0]
        for r in results:
            rname = (r.get("name") or "").lower()
            if rname == name_l or name_l in rname or rname in name_l:
                best = r
                break

        label = best.get("name", name)
        admin = best.get("admin1") or best.get("country") or ""
        if admin and admin.lower() not in label.lower():
            label = f"{label}, {admin}"

        return float(best["latitude"]), float(best["longitude"]), label

    @staticmethod
    async def _fetch(lat: float, lon: float, timezone: str) -> dict:
        import aiohttp

        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": ["weathercode", "temperature_2m_max", "temperature_2m_min",
                      "precipitation_sum"],
            "current_weather": "true",
            "timezone": timezone,
            "forecast_days": 7,
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
    def _day_index(dates: list[str], when: str, tz: ZoneInfo) -> tuple[int, str]:
        if not dates:
            return 0, "Oggi"

        if when == "today":
            return 0, "Oggi"
        if when == "tomorrow":
            return min(1, len(dates) - 1), "Domani"
        if when == "after_tomorrow":
            return min(2, len(dates) - 1), "Dopodomani"

        if when.startswith("weekday:"):
            target = int(when.split(":", 1)[1])
            today = datetime.now(tz).date()
            names = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
            for i, date_str in enumerate(dates):
                d = date.fromisoformat(date_str)
                if d >= today and d.weekday() == target:
                    return i, names[target].capitalize()
            return 0, "Oggi"

        return 0, "Oggi"

    @staticmethod
    def _format_response(data: dict, when: str, place: str, tz: ZoneInfo) -> str:
        daily = data.get("daily", {})
        dates = daily.get("time", [])
        codes = daily.get("weathercode", [])
        max_t = daily.get("temperature_2m_max", [])
        min_t = daily.get("temperature_2m_min", [])

        if not dates:
            return "Non ho dati meteo disponibili."

        idx, day_label = WeatherSkill._day_index(dates, when, tz)
        if idx >= len(dates):
            idx = 0
            day_label = "Oggi"

        code = codes[idx] if idx < len(codes) else 0
        desc = WMO_CODES.get(code, "condizioni variabili")
        t_max = max_t[idx] if idx < len(max_t) else "?"
        t_min = min_t[idx] if idx < len(min_t) else "?"

        where = f" a {place}" if place else ""
        return (
            f"{day_label}{where} le previsioni indicano {desc}, "
            f"con temperature tra {t_min}° e {t_max}°C."
        )
