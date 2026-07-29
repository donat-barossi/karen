"""
Karen – Pipeline principale

Sequenza per ogni richiesta vocale:
  1. Audio PCM → ASR (Whisper transcribe IT) → testo IT
  2. Testo IT  → LLM (Phi-3 Mini) o fast-path → JSON intent
  3. JSON      → Skill engine                  → risposta IT
  4. Risposta  → TTS (Piper Paola)             → audio PCM @ 16 kHz
"""

from __future__ import annotations

import json
import logging
import re
import time
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .audio_util import normalize_pcm16, resample_pcm16, trim_silence_pcm16
from .recipes import curated_recipe_for, detect_curated_dish, normalize_recipe_query
from .tts_text import format_recipe_for_speech, prepare_text_for_tts

from .scheduling import ScheduleService
from .scheduling.ringing import is_dismiss_phrase
from .asr import WhisperASR
from .llm import LLMEngine
from .tts import PiperTTS
from .skills import SkillRegistry
from .skills.timer_skill import (
    parse_alarm_intent,
    parse_timer_duration,
    parse_timer_intent,
)

log = logging.getLogger(__name__)

ESP32_SAMPLE_RATE = 16000
CLARIFY_MSG = "Non ho capito. Puoi ripetere?"
GIVE_UP_MSG = "Ok, ci sentiamo dopo."

_CANCEL_DIALOG = frozenset({
    "stop", "no", "basta", "esci", "fine", "silenzio",
    "lascia stare", "lascia perdere", "ok basta", "niente", "nulla",
    "chiudi", "cancel", "quit",
})


@dataclass
class PipelineResult:
    audio: bytes
    listen_again: bool = False

_WAKE_RE = re.compile(
    r"\b(hey|ehi)\s*(kira|karen|cira|chira|caro|carina)\b",
    re.IGNORECASE,
)


def _clean_transcript(text: str) -> str:
    t = _WAKE_RE.sub("", text)
    t = re.sub(r"[^\w\s']", " ", t.lower())
    return re.sub(r"\s+", " ", t).strip()


_JUNK_ASR_RE = re.compile(
    r"sottotitoli|revisione a cura|qtss|amara\.org|iscriviti al canale",
    re.I,
)


class KarenPipeline:
    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg
        models_dir = Path(__file__).parent.parent / "models"

        self._schedule = ScheduleService(cfg)
        cfg["schedule_service"] = self._schedule
        self._last_spoken: str = ""
        self._clarify_streak: int = 0

        self.asr = WhisperASR(cfg["asr"], models_dir)
        self.llm = LLMEngine(cfg["llm"], models_dir)
        self.tts = PiperTTS(cfg["tts"], models_dir)
        self.skills = SkillRegistry(cfg)

    async def initialize(self) -> None:
        """Carica tutti i modelli in memoria (eseguito all'avvio)."""
        log.info("Caricamento modelli…")
        t0 = time.monotonic()

        self.asr.load()
        log.info("  ✓ ASR (Whisper small)")

        self.llm.load()
        log.info("  ✓ LLM (Phi-3 Mini)")

        self.tts.load()
        log.info("  ✓ TTS (Piper)")

        await self._schedule.start()
        await self.skills.initialize()
        log.info("  ✓ Skills")

        log.info("Modelli pronti in %.1f s", time.monotonic() - t0)

    def set_voice_announce(self, callback: Any) -> None:
        self._schedule.set_voice_announce(callback)

    def set_ring_controller(self, ring: Any) -> None:
        self._cfg["ring_controller"] = ring
        self._schedule.set_ring_controller(ring)

    async def transcribe_only(self, audio_pcm16: bytes) -> str:
        audio_pcm16 = trim_silence_pcm16(audio_pcm16, ESP32_SAMPLE_RATE)
        return await asyncio.to_thread(
            lambda: _clean_transcript(self.asr.transcribe(audio_pcm16))
        )

    async def process(self, audio_pcm16: bytes) -> PipelineResult:
        """Pipeline completa; ASR/LLM/TTS in thread pool, skills async."""
        t_start = time.monotonic()

        audio_pcm16 = trim_silence_pcm16(audio_pcm16, ESP32_SAMPLE_RATE)
        duration_s = len(audio_pcm16) / (ESP32_SAMPLE_RATE * 2)

        text_it = await asyncio.to_thread(
            lambda: _clean_transcript(self.asr.transcribe(audio_pcm16))
        )
        log.info("ASR → '%s'  (%.2f s)", text_it, time.monotonic() - t_start)

        if self._is_junk_transcript(text_it):
            log.warning("ASR hallucination ignorata: '%s'", text_it)
            text_it = ""

        if self._is_cancel_dialog(text_it):
            log.info("Interruzione dialogo: '%s'", text_it)
            self._clarify_streak = 0
            return await self._finish("Ok, va bene.", listen_again=False)

        if not text_it.strip():
            if self._clarify_streak >= 1:
                log.info("Silenzio dopo chiarimento, chiusura dialogo")
                self._clarify_streak = 0
                return await self._finish(GIVE_UP_MSG, listen_again=False)
            return await self._clarify()

        if duration_s < 0.25 and not self._is_cancel_dialog(text_it):
            log.warning("Audio troppo corto (%.2f s), chiedo ripetizione", duration_s)
            return await self._clarify()

        if self._looks_like_transcript_echo(text_it):
            log.warning("ASR probabile eco TTS, ignorato: '%s'", text_it)
            if self._clarify_streak >= 1:
                self._clarify_streak = 0
                return await self._finish(GIVE_UP_MSG, listen_again=False)
            return await self._clarify()

        if self._looks_like_recipe_query(text_it):
            self._clarify_streak = 0
            query = normalize_recipe_query(text_it)
            curated = curated_recipe_for(text_it)
            if curated:
                log.info("Ricetta curata (%s, query=%r)", detect_curated_dish(text_it), query)
                spoken = format_recipe_for_speech(curated)
            else:
                log.info("Richiesta ricetta → LLM (query=%r)", query)
                try:
                    recipe = await asyncio.to_thread(self.llm.generate_recipe, query)
                except Exception as e:
                    log.exception("Errore LLM ricetta: %s", e)
                    return await self._clarify()
                if not recipe.strip():
                    return await self._clarify()
                spoken = format_recipe_for_speech(recipe)
            log.info("Ricetta TTS (%d char) → '%s'", len(spoken), spoken)
            return await self._finish(spoken, listen_again=False)

        t_llm = time.monotonic()
        intent_data = self._fast_intent(text_it)
        if intent_data is not None:
            log.info(
                "Fast-path intent=%s  (%.2f s)",
                intent_data.get("intent"),
                time.monotonic() - t_llm,
            )
        else:
            raw_response = await asyncio.to_thread(self.llm.generate, text_it)
            log.info("LLM → '%s'  (%.2f s)", raw_response[:120], time.monotonic() - t_llm)
            intent_data = self._parse_intent(raw_response, text_it)

        if intent_data.get("intent") in ("general", "unknown", None):
            resp = intent_data.get("response_it", "")
            if not resp or resp.startswith("[SKILL") or "non ho capito" in resp.lower():
                return await self._clarify()

        t_skill = time.monotonic()
        response_it = await self.skills.execute(intent_data)
        log.info("Skill → '%s'  (%.2f s)", response_it, time.monotonic() - t_skill)
        self._last_spoken = response_it
        self._clarify_streak = 0

        listen_again = self._should_listen_again(response_it)

        t_tts = time.monotonic()
        audio_out = await asyncio.to_thread(self._synthesize_phrase, response_it)
        log.info(
            "TTS → %d campioni @ %d Hz  (%.2f s)",
            len(audio_out) // 2,
            ESP32_SAMPLE_RATE,
            time.monotonic() - t_tts,
        )

        log.info("Pipeline totale: %.2f s", time.monotonic() - t_start)
        return PipelineResult(audio_out, listen_again=listen_again)

    async def _finish(self, message: str, *, listen_again: bool) -> PipelineResult:
        self._last_spoken = message
        pcm = await asyncio.to_thread(self._synthesize_phrase, message)
        return PipelineResult(pcm, listen_again=listen_again)

    async def _clarify(self, message: str = CLARIFY_MSG) -> PipelineResult:
        self._clarify_streak += 1
        max_retries = int(self._cfg.get("pipeline", {}).get("clarify_max_retries", 2))
        if self._clarify_streak > max_retries:
            log.info("Troppi tentativi chiarimento (%d), chiusura dialogo", self._clarify_streak)
            self._clarify_streak = 0
            return await self._finish(GIVE_UP_MSG, listen_again=False)
        return await self._finish(message, listen_again=True)

    @staticmethod
    def _should_listen_again(response_it: str) -> bool:
        t = response_it.lower()
        return any(
            p in t
            for p in ("non ho capito", "puoi ripetere", "a che ora")
        )

    def _synthesize_phrase(self, text: str) -> bytes:
        text = prepare_text_for_tts(text)
        pcm = self.tts.synthesize(text)
        pcm = resample_pcm16(pcm, self.tts.sample_rate, ESP32_SAMPLE_RATE)
        return normalize_pcm16(pcm)

    def _normalize_user_text(self, text: str) -> str:
        t = text.lower().strip()
        for wake in ("hey kira", "ehi kira", "hey karen", "ehi karen", "karen"):
            t = t.replace(wake, " ")
        t = re.sub(r"[^\w\s']", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    def _is_junk_transcript(self, text: str) -> bool:
        return bool(text.strip()) and bool(_JUNK_ASR_RE.search(text))

    def _looks_like_recipe_query(self, text: str) -> bool:
        t = self._normalize_user_text(text)
        if re.search(
            r"ricetta|"
            r"come\s+(?:si\s+)?(?:prepar\w*|facc\w*|fai\w*|fate\w*|cucin\w*|cuoc\w*)|"
            r"ingredienti\s+(?:per|della|del|di)",
            t,
        ):
            return True
        if any(
            p in t
            for p in (
                "come si prepara",
                "come si fa",
                "come cucinare",
                "ingredienti per",
                "come fare la",
                "come fare il",
            )
        ):
            return True
        dishes = (
            "carbonara",
            "amatriciana",
            "cacio e pepe",
            "lasagne",
            "risotto",
            "tiramisu",
            "pizza",
        )
        if any(d in t for d in dishes) and any(
            w in t for w in ("come", "prepar", "ricetta", "ingredienti", "cucin")
        ):
            return True
        return False

    def _is_cancel_dialog(self, text: str) -> bool:
        t = self._normalize_user_text(text)
        if not t:
            return False
        if parse_alarm_intent(t) is not None:
            return False
        if parse_timer_intent(t) is not None:
            return False
        if t in _CANCEL_DIALOG:
            return True
        first = t.split()[0] if t.split() else ""
        return first in _CANCEL_DIALOG

    def _looks_like_time_query(self, text: str) -> bool:
        t = self._normalize_user_text(text)
        collapsed = t.replace(" ", "")
        if any(p in t for p in ("che ore", "che ora", "dimmi l'ora", "ora sono")):
            return True
        if any(token in collapsed for token in ("orisono", "oresono", "orasono", "orae sono")):
            return True
        return bool(re.search(r"(che\s*)?or[aei]{1,2}\s*sono", t))

    def _looks_like_transcript_echo(self, text: str) -> bool:
        """Scarta trascrizioni che replicano l'ultima risposta TTS (eco altoparlante)."""
        if not self._last_spoken:
            return False
        t = self._normalize_user_text(text)
        spoken = self._normalize_user_text(self._last_spoken)
        if not t or not spoken:
            return False
        if t == spoken or spoken in t:
            return True
        if "sveglia alle sette" in t and "impostata" in spoken:
            return True
        return False

    def _fast_intent(self, text: str) -> dict[str, Any] | None:
        """
        Bypass LLM per comandi frequenti: più veloce e risposta sempre in italiano.
        """
        t = self._normalize_user_text(text)

        ring = self._cfg.get("ring_controller")
        if ring and getattr(ring, "is_active", False) and is_dismiss_phrase(t):
            return {**self._intent("ringing"), "parameters": {"action": "dismiss"}}

        if self._is_cancel_dialog(text):
            self._clarify_streak = 0
            return {
                **self._intent("general"),
                "response_it": "Ok, va bene.",
            }

        if self._looks_like_time_query(text):
            return self._intent("time")

        if any(p in t for p in ("che giorno", "che data", "data di oggi", "data è oggi")):
            return self._intent("date")

        if any(p in t for p in ("che tempo", "meteo", "tempo fuori", "farà")):
            return {
                **self._intent("weather"),
                "parameters": {"when": "today"},
            }

        timer_intent = parse_timer_intent(t)
        if timer_intent is not None:
            return timer_intent

        alarm_intent = parse_alarm_intent(t)
        if alarm_intent is not None:
            return alarm_intent

        duration = parse_timer_duration(t)
        if duration is not None:
            return {**self._intent("timer"), "parameters": {"duration_s": duration, "action": "start"}}

        if any(p in t for p in ("calendario", "agenda", "appuntament")):
            when = "tomorrow" if "domani" in t else "today"
            return {**self._intent("calendar_query"), "parameters": {"when": when}}

        greetings = ("ciao", "salve", "buongiorno", "buonasera", "come stai")
        if t in greetings or (t.startswith("ciao ") and len(t) < 24):
            return {
                **self._intent("general"),
                "response_it": "Ciao! Sono Karen, come posso aiutarti?",
            }

        return None

    @staticmethod
    def _intent(name: str) -> dict[str, Any]:
        return {
            "intent": name,
            "parameters": {},
            "response_it": "[SKILL_WILL_FILL]",
            "ha_service": None,
            "ha_entity": None,
        }

    def _parse_intent(self, raw: str, text_it: str = "") -> dict[str, Any]:
        """Estrae il JSON dall'output LLM (tollera testo extra)."""
        raw = raw.strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            log.warning("LLM non ha restituito JSON valido: %s", raw[:200])
            if text_it:
                fb = self._fast_intent(text_it)
                if fb:
                    return fb
            return {
                "intent": "general",
                "parameters": {},
                "response_it": "Non ho capito bene. Puoi ripetere?",
            }
        try:
            data = json.loads(raw[start:end])
        except json.JSONDecodeError as e:
            log.warning("JSON parse error: %s | raw: %s", e, raw[:200])
            recovered = self._recover_recipe_from_raw(raw, text_it)
            if recovered:
                return recovered
            if text_it:
                fb = self._fast_intent(text_it)
                if fb:
                    return fb
            return {
                "intent": "general",
                "parameters": {},
                "response_it": "Non ho capito. Puoi ripetere?",
            }

        intent = data.get("intent")
        if not intent or intent in ("unknown", "general"):
            if text_it:
                fb = self._fast_intent(text_it)
                if fb:
                    return fb
            normalized = self._normalize_llm_intent(data, text_it)
            if normalized.get("intent"):
                return normalized

        if not data.get("intent"):
            log.warning("Intent mancante dopo LLM: %s | testo=%r", data, text_it)
            recovered = self._recover_recipe_from_llm_data(data, text_it)
            if recovered:
                return recovered
            if text_it:
                fb = self._fast_intent(text_it)
                if fb:
                    return fb
            return {
                "intent": "general",
                "parameters": {},
                "response_it": "Non ho capito. Puoi ripetere?",
            }
        return data

    def _recover_recipe_from_raw(self, raw: str, text_it: str) -> dict[str, Any] | None:
        if not self._looks_like_recipe_query(text_it):
            return None
        for pattern in (
            r'"response_it"\s*:\s*"((?:[^"\\]|\\.)*)',
            r'"ricetta"\s*:\s*"((?:[^"\\]|\\.)*)',
            r'"response"\s*:\s*"((?:[^"\\]|\\.)*)',
        ):
            m = re.search(pattern, raw)
            if m:
                text = m.group(1).replace("\\n", " ").strip()
                if len(text) > 20:
                    return {**self._intent("recipe"), "response_it": text[:600]}
        return None

    def _recover_recipe_from_llm_data(
        self, data: dict[str, Any], text_it: str
    ) -> dict[str, Any] | None:
        if not self._looks_like_recipe_query(text_it):
            return None
        for key in ("response_it", "ricetta", "response", "instructions"):
            val = data.get(key)
            if isinstance(val, str) and len(val.strip()) > 20:
                return {**self._intent("recipe"), "response_it": val.strip()[:600]}
        title = data.get("title")
        ingredients = data.get("ingredients")
        if isinstance(title, str) and isinstance(ingredients, list) and ingredients:
            ing = ", ".join(str(i) for i in ingredients[:6])
            text = f"{title}: ingredienti {ing}."
            return {**self._intent("recipe"), "response_it": text[:600]}
        return None

    def _normalize_llm_intent(self, data: dict[str, Any], text_it: str) -> dict[str, Any]:
        """Recupera intent da JSON LLM malformato (es. action/action_params)."""
        if data.get("intent"):
            return data

        recovered = self._recover_recipe_from_llm_data(data, text_it)
        if recovered:
            return recovered

        t = self._normalize_user_text(text_it)
        action = str(data.get("action", "")).lower()
        params = data.get("parameters") or data.get("action_params") or {}

        if action in ("start", "cancel", "list") or "timer" in t or "minut" in t:
            if action == "cancel" or any(p in t for p in ("annulla", "cancella", "ferma")):
                return {
                    **self._intent("timer"),
                    "parameters": {"action": "cancel", "all": "tutti" in t},
                }
            if action == "list" or any(p in t for p in ("quali timer", "timer attivi")):
                return {**self._intent("timer"), "parameters": {"action": "list"}}

            duration = parse_timer_duration(t)
            if duration is None and isinstance(params.get("timer_duration"), str):
                duration = parse_timer_duration(params["timer_duration"])
            if duration is None and isinstance(params.get("duration_s"), (int, float)):
                duration = int(params["duration_s"])
            if duration is not None:
                return {
                    **self._intent("timer"),
                    "parameters": {"action": "start", "duration_s": duration},
                }

        return data

    async def shutdown(self) -> None:
        log.info("Pipeline: shutdown")
        await self._schedule.stop()
        await self.skills.shutdown()
