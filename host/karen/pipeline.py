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
from pathlib import Path
from typing import Any

from .audio_util import normalize_pcm16, resample_pcm16, trim_silence_pcm16

from .asr import WhisperASR
from .llm import LLMEngine
from .tts import PiperTTS
from .skills import SkillRegistry
from .skills.timer_skill import parse_alarm_time, parse_timer_duration

log = logging.getLogger(__name__)

ESP32_SAMPLE_RATE = 16000

_WAKE_RE = re.compile(
    r"\b(hey|ehi)\s*(kira|karen|cira|chira|caro|carina)\b",
    re.IGNORECASE,
)


def _clean_transcript(text: str) -> str:
    t = _WAKE_RE.sub("", text)
    return re.sub(r"\s+", " ", t).strip(" ,.")


class KarenPipeline:
    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg
        models_dir = Path(__file__).parent.parent / "models"

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

        await self.skills.initialize()
        log.info("  ✓ Skills")

        log.info("Modelli pronti in %.1f s", time.monotonic() - t0)

    async def process(self, audio_pcm16: bytes) -> bytes:
        """Pipeline completa; ASR/LLM/TTS in thread pool, skills async."""
        t_start = time.monotonic()

        audio_pcm16 = trim_silence_pcm16(audio_pcm16, ESP32_SAMPLE_RATE)

        text_it = await asyncio.to_thread(
            lambda: _clean_transcript(self.asr.transcribe(audio_pcm16))
        )
        log.info("ASR → '%s'  (%.2f s)", text_it, time.monotonic() - t_start)

        if not text_it.strip():
            return await asyncio.to_thread(self._synthesize_phrase, "Non ho capito. Puoi ripetere?")

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

        t_skill = time.monotonic()
        response_it = await self.skills.execute(intent_data)
        log.info("Skill → '%s'  (%.2f s)", response_it, time.monotonic() - t_skill)

        t_tts = time.monotonic()
        audio_out = await asyncio.to_thread(self._synthesize_phrase, response_it)
        log.info(
            "TTS → %d campioni @ %d Hz  (%.2f s)",
            len(audio_out) // 2,
            ESP32_SAMPLE_RATE,
            time.monotonic() - t_tts,
        )

        log.info("Pipeline totale: %.2f s", time.monotonic() - t_start)
        return audio_out

    def _synthesize_phrase(self, text: str) -> bytes:
        pcm = self.tts.synthesize(text)
        pcm = resample_pcm16(pcm, self.tts.sample_rate, ESP32_SAMPLE_RATE)
        return normalize_pcm16(pcm)

    def _normalize_user_text(self, text: str) -> str:
        t = text.lower().strip()
        for wake in ("hey kira", "ehi kira", "hey karen", "ehi karen", "karen"):
            t = t.replace(wake, " ")
        t = re.sub(r"[^\w\s']", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    def _looks_like_time_query(self, text: str) -> bool:
        t = self._normalize_user_text(text)
        collapsed = t.replace(" ", "")
        if any(p in t for p in ("che ore", "che ora", "dimmi l'ora", "ora sono")):
            return True
        if any(token in collapsed for token in ("orisono", "oresono", "orasono", "orae sono")):
            return True
        return bool(re.search(r"(che\s*)?or[aei]{1,2}\s*sono", t))

    def _fast_intent(self, text: str) -> dict[str, Any] | None:
        """
        Bypass LLM per comandi frequenti: più veloce e risposta sempre in italiano.
        """
        t = self._normalize_user_text(text)

        if self._looks_like_time_query(text):
            return self._intent("time")

        if any(p in t for p in ("che giorno", "che data", "data di oggi", "data è oggi")):
            return self._intent("date")

        if any(p in t for p in ("che tempo", "meteo", "tempo fuori", "farà")):
            return {
                **self._intent("weather"),
                "parameters": {"when": "today"},
            }

        duration = parse_timer_duration(t)
        if duration is not None:
            return {**self._intent("timer"), "parameters": {"duration_s": duration}}

        alarm = parse_alarm_time(t)
        if alarm is not None:
            h, m = alarm
            return {**self._intent("alarm"), "parameters": {"hour": h, "minute": m}}

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
        return data

    async def shutdown(self) -> None:
        log.info("Pipeline: shutdown")
        await self.skills.shutdown()
