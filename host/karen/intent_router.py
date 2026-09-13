"""
Router intent ibrido: regole deterministiche + riconciliazione output LLM.

Le regole vincono su alarm/timer/music (parametri precisi, bassa latenza).
L'LLM copre il resto; se sbaglia schema o intent, recuperiamo dalle regole.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .asr_fix import fix_asr_transcript
from .skills.music_skill import parse_music_intent
from .skills.weather_skill import parse_weather_intent
from .skills.timer_skill import (
    parse_alarm_intent,
    parse_timer_duration,
    parse_timer_intent,
)

log = logging.getLogger(__name__)

_STRUCTURED_INTENTS = frozenset({"alarm", "timer", "music"})

VALID_INTENTS = frozenset({
    "timer", "alarm", "calendar_query", "calendar_create", "reminder",
    "ha_action", "weather", "time", "date", "recipe", "music",
    "general", "unknown", "ringing",
})

_MAX_RESPONSE_CHARS = 180

_LLM_ALARM_DEVICE = re.compile(r"alarm|svegl", re.I)


def match_rule_intent(text: str) -> dict[str, Any] | None:
    """
    Fast-path deterministico su testo già ripulito da ASR.
    Priorità: sveglie → timer → musica.
    """
    t = fix_asr_transcript(text)
    if not t:
        return None

    alarm = parse_alarm_intent(t)
    if alarm is not None:
        return alarm

    timer = parse_timer_intent(t)
    if timer is not None:
        return timer

    duration = parse_timer_duration(t)
    if duration is not None:
        return {
            "intent": "timer",
            "parameters": {"action": "start", "duration_s": duration},
        }

    music = parse_music_intent(t)
    if music is not None:
        return music

    weather = parse_weather_intent(t)
    if weather is not None:
        return weather

    return None


def is_llm_schema_invalid(data: dict[str, Any]) -> bool:
    """True se l'LLM ha ignorato lo schema JSON atteso."""
    if not data:
        return True
    if data.get("intent"):
        return False
    if any(k in data for k in ("command", "device", "action", "note", "message")):
        return True
    if "parameters" not in data and "action_params" not in data:
        return bool(data.keys() - {"response_it", "response", "ricetta"})
    return False


def recover_intent_from_llm_data(data: dict[str, Any], text: str) -> dict[str, Any] | None:
    """Mappa JSON LLM malformato verso intent noti."""
    t = fix_asr_transcript(text.lower())

    rule = match_rule_intent(text)
    if rule is not None:
        return rule

    command = str(data.get("command", "")).lower()
    device = str(data.get("device", "")).lower()
    action = str(data.get("action", "")).lower()
    location = str(data.get("location", "")).lower()

    if command in ("turn_off", "remove", "delete", "cancel", "disable") and (
        _LLM_ALARM_DEVICE.search(device) or re.search(r"\bsvegl", t)
    ):
        return {
            "intent": "alarm",
            "parameters": {
                "action": "cancel",
                "all": location == "all" or bool(re.search(r"\btutt[ei]\b", t)),
            },
        }

    if action in ("set", "create", "start") and re.search(r"\bsvegl", t):
        alarm = parse_alarm_intent(t)
        if alarm is not None:
            return alarm

    if action in ("cancel", "stop", "disable") and re.search(r"\btimer\b", t):
        return {
            "intent": "timer",
            "parameters": {"action": "cancel", "all": "tutti" in t},
        }

    note = data.get("note") or data.get("message") or data.get("response")
    if isinstance(note, str) and len(note) > 40 and re.search(r"\bsvegl", t):
        alarm = parse_alarm_intent(t)
        if alarm is not None:
            log.info("Ignoro risposta LLM generica, uso regole sveglia")
            return alarm

    return None


def reconcile_intent(text: str, llm_data: dict[str, Any] | None) -> dict[str, Any] | None:
    """
    Unisce output LLM e regole.
    Per alarm/timer/music preferisce le regole se l'LLM è assente o in conflitto.
    """
    rule = match_rule_intent(text)

    if llm_data is None:
        return rule

    if is_llm_schema_invalid(llm_data):
        recovered = recover_intent_from_llm_data(llm_data, text)
        if recovered is not None:
            log.info(
                "Intent recuperato da schema LLM invalido → %s",
                recovered.get("intent"),
            )
            return recovered
        if rule is not None:
            return rule
        return None

    llm_intent = llm_data.get("intent")
    if rule is not None and rule.get("intent") in _STRUCTURED_INTENTS:
        rule_intent = rule.get("intent")
        if not llm_intent or llm_intent in ("unknown", "general"):
            log.info("Preferisco regole (%s) su LLM vuoto", rule_intent)
            return rule
        if llm_intent != rule_intent and rule_intent in ("alarm", "timer"):
            log.info(
                "Preferisco regole (%s) su LLM (%s) per testo=%r",
                rule_intent,
                llm_intent,
                text[:80],
            )
            return rule
        if rule_intent == llm_intent == "alarm":
            rule_params = rule.get("parameters", {})
            llm_params = llm_data.get("parameters", {})
            if rule_params.get("action") == "set" and "hour" in rule_params:
                if llm_params.get("hour") != rule_params.get("hour") or (
                    llm_params.get("minute") != rule_params.get("minute")
                ):
                    log.info("Preferisco ora da regole: %s", rule_params)
                    return {**llm_data, "parameters": rule_params, "intent": "alarm"}

    return llm_data


def recover_general_response(llm_data: dict[str, Any]) -> dict[str, Any] | None:
    """
    L'LLM a volte inventa intent (es. 'Inquiry about chemical composition')
    ma fornisce una response_it valida: usala come intent general.
    """
    resp = llm_data.get("response_it") or llm_data.get("response") or ""
    if not isinstance(resp, str):
        return None
    resp = resp.strip()
    if not resp or resp.startswith("[SKILL") or len(resp) < 8:
        return None
    low = resp.lower()
    if any(p in low for p in (
        "non ho capito", "puoi ripetere", "non so rispondere",
        "non possiamo fornire", "ulteriori informazioni", "senza ulteriori",
    )):
        return None
    if is_weak_general_response(resp):
        return None
    return {
        "intent": "general",
        "parameters": llm_data.get("parameters") if isinstance(llm_data.get("parameters"), dict) else {},
        "response_it": resp,
        "ha_service": None,
        "ha_entity": None,
    }


def is_weak_general_response(resp: str) -> bool:
    """Risposte LLM generiche/domande al posto di una risposta utile."""
    low = resp.strip().lower()
    if not low:
        return True
    if "?" in resp:
        return True
    return any(p in low for p in (
        "che cosa è successo",
        "vuoi sapere",
        "cosa intendi",
        "puoi essere più specifico",
        "eventi specifici",
        "i fatti o",
        "ulteriori dettagli",
        "cosa vuoi sapere",
        "puoi chiarire",
        "non possiamo fornire",
    ))


def is_valid_intent(intent: str | None) -> bool:
    if not intent or not isinstance(intent, str):
        return False
    return intent.strip().lower() in VALID_INTENTS


def cap_spoken_response(text: str, *, max_chars: int = _MAX_RESPONSE_CHARS) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].strip()
    return (cut or text[:max_chars]).rstrip(".,;:") + "."
