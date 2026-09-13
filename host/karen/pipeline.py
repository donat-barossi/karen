"""
Karen – Pipeline principale

Sequenza per ogni richiesta vocale:
  1. Audio PCM → ASR (Whisper transcribe IT) → testo IT
  2. Testo IT  → LLM (Phi-3 Mini) o fast-path → JSON intent
  3. JSON      → Skill engine                  → risposta IT
  4. Risposta  → TTS (Piper Giorgio)             → audio PCM @ 16 kHz
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

from .assistant import assistant_greeting
from .asr_fix import fix_asr_transcript
from .audio_util import normalize_pcm16, resample_pcm16, trim_silence_pcm16
from .recipes import curated_recipe_for, detect_curated_dish, normalize_recipe_query
from .tts_text import format_recipe_for_speech, prepare_text_for_tts

from .scheduling import ScheduleService
from .scheduling.ringing import is_dismiss_phrase
from .stop import is_global_stop_phrase
from .media_control import (
    is_global_next_phrase,
    is_global_pause_phrase,
    is_global_previous_phrase,
    is_global_repeat_phrase,
    is_global_resume_phrase,
)
from .ha_client import HaCallResult, HomeAssistantClient, ha_action_error
from .asr_factory import create_asr
from .llm import LLMEngine
from .tts import PiperTTS
from .skills import SkillRegistry
from .skills.timer_skill import (
    parse_alarm_intent,
    parse_timer_intent,
)
from .skills.weather_skill import parse_weather_intent
from .intent_router import (
    cap_spoken_response,
    is_valid_intent,
    match_rule_intent,
    reconcile_intent,
    recover_general_response,
    recover_intent_from_llm_data,
    is_weak_general_response,
)

log = logging.getLogger(__name__)

ESP32_SAMPLE_RATE = 16000
HA_CONTROL_TIMEOUT_S = 2.0
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
    r"\b(hey|ehi|hi)\s*(jarvis|kira|karen|cira|chira|caro|carina)\b|\bjarvis\b",
    re.IGNORECASE,
)


def _clean_transcript(text: str) -> str:
    t = _WAKE_RE.sub("", text)
    t = re.sub(r"[^\w\s']", " ", t.lower())
    t = re.sub(r"\s+", " ", t).strip()
    return fix_asr_transcript(t)


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
        self._last_pcm: bytes = b""
        self._last_music_intent: dict[str, Any] | None = None
        self._playback_paused: bool = False
        self._transport: Any = None
        self._clarify_streak: int = 0

        self.asr = create_asr(cfg["asr"], models_dir)
        self.llm = LLMEngine(cfg["llm"], models_dir, root_cfg=cfg)
        self.tts = PiperTTS(cfg["tts"], models_dir)
        self.skills = SkillRegistry(cfg)

    async def initialize(self) -> None:
        """Carica tutti i modelli in memoria (eseguito all'avvio)."""
        log.info("Caricamento modelli…")
        t0 = time.monotonic()

        # Orin 8GB: riserva GPU/unified memory per Phi-3 prima di Whisper CPU.
        if self._cfg.get("platform") == "jetson":
            self.llm.load()
            log.info("  ✓ LLM (Phi-3 Mini)")
            self.asr.load()
            log.info("  ✓ ASR (Whisper small)")
        else:
            self.asr.load()
            log.info("  ✓ ASR (Whisper small)")
            self.llm.load()
            log.info("  ✓ LLM (Phi-3 Mini)")

        self.tts.load()
        log.info("  ✓ TTS (Piper Giorgio)")

        await self._schedule.start()
        await self.skills.initialize()
        log.info("  ✓ Skills")

        log.info("Modelli pronti in %.1f s", time.monotonic() - t0)

    def set_voice_announce(self, callback: Any) -> None:
        self._schedule.set_voice_announce(callback)

    def set_ring_controller(self, ring: Any) -> None:
        self._cfg["ring_controller"] = ring
        self._schedule.set_ring_controller(ring)

    def set_transport(self, transport: Any) -> None:
        self._transport = transport

    async def transcribe_ring_dismiss(self, audio_pcm16: bytes) -> str:
        """ASR ottimizzato per 'stop' durante sveglia: no trim, prompt dedicato."""
        return await asyncio.to_thread(
            lambda: _clean_transcript(self.asr.transcribe_ring_dismiss(audio_pcm16))
        )

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

        if text_it and self._looks_like_time_query(text_it):
            log.info("Ora fast-path: '%s'", text_it)
            self._clarify_streak = 0
            response_it = await self.skills.execute(self._intent("time"))
            return await self._finish(response_it, listen_again=False)

        if not self._is_ring_active():
            if is_global_pause_phrase(text_it):
                log.info("Pausa globale: '%s'", text_it)
                self._clarify_streak = 0
                return await self._handle_global_pause()
            if is_global_resume_phrase(text_it):
                log.info("Riprendi globale: '%s'", text_it)
                self._clarify_streak = 0
                return await self._handle_global_resume()
            if is_global_repeat_phrase(text_it):
                log.info("Ripeti globale: '%s'", text_it)
                self._clarify_streak = 0
                return await self._handle_global_repeat()
            if is_global_next_phrase(text_it):
                log.info("Brano successivo: '%s'", text_it)
                self._clarify_streak = 0
                return await self._handle_global_next()
            if is_global_previous_phrase(text_it):
                log.info("Brano precedente: '%s'", text_it)
                self._clarify_streak = 0
                return await self._handle_global_previous()

        rule_intent = match_rule_intent(text_it)
        if (
            rule_intent is not None
            and rule_intent.get("intent") in ("alarm", "timer")
            and not self._is_ring_active()
        ):
            log.info(
                "Rule fast-path intent=%s: '%s'",
                rule_intent.get("intent"),
                text_it,
            )
            self._clarify_streak = 0
            response_it = await self.skills.execute(rule_intent)
            return await self._finish(response_it, listen_again=False)

        if is_global_stop_phrase(text_it):
            log.info("Stop globale: '%s'", text_it)
            self._clarify_streak = 0
            return await self._handle_global_stop()

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
            reconciled = reconcile_intent(text_it, intent_data)
            if reconciled is not None:
                intent_data = reconciled

        if not is_valid_intent(intent_data.get("intent")):
            recovered = recover_general_response(intent_data)
            if recovered is not None:
                log.info(
                    "Intent LLM non valido %r → risposta general",
                    intent_data.get("intent"),
                )
                intent_data = recovered
            else:
                log.warning(
                    "Intent LLM non valido: %r → regole o chiarimento",
                    intent_data.get("intent"),
                )
                rule = match_rule_intent(text_it)
                if rule is not None:
                    intent_data = rule
                elif self._looks_like_time_query(text_it):
                    intent_data = self._intent("time")
                else:
                    return await self._clarify()

        if intent_data.get("intent") in ("general", "unknown", None):
            resp = intent_data.get("response_it", "")
            if (
                not resp
                or resp.startswith("[SKILL")
                or "non ho capito" in resp.lower()
                or is_weak_general_response(resp)
            ):
                if self._looks_like_time_query(text_it):
                    intent_data = self._intent("time")
                else:
                    return await self._clarify()

        t_skill = time.monotonic()
        response_it = await self.skills.execute(intent_data)
        response_it = cap_spoken_response(response_it)
        log.info("Skill → '%s'  (%.2f s)", response_it, time.monotonic() - t_skill)
        self._last_spoken = response_it
        self._clarify_streak = 0
        if intent_data.get("intent") == "music":
            params = intent_data.get("parameters", {})
            if params.get("action") == "play" and params.get("query"):
                self._last_music_intent = intent_data

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
        self._last_pcm = audio_out
        self._playback_paused = False
        return PipelineResult(audio_out, listen_again=listen_again)

    async def _finish(self, message: str, *, listen_again: bool) -> PipelineResult:
        self._last_spoken = message
        pcm = await asyncio.to_thread(self._synthesize_phrase, message)
        self._last_pcm = pcm
        self._playback_paused = False
        return PipelineResult(pcm, listen_again=listen_again)

    def _is_ring_active(self) -> bool:
        ring = self._cfg.get("ring_controller")
        return bool(ring and getattr(ring, "is_active", False))

    async def _abort_playback_if_any(self) -> None:
        transport = self._transport
        if transport and hasattr(transport, "abort_playback"):
            await transport.abort_playback()

    def _music_entity(self) -> str | None:
        music_cfg = self._cfg.get("music", {})
        ha_cfg = self._cfg.get("ha", {})
        return (
            music_cfg.get("media_player")
            or ha_cfg.get("entities", {}).get("media_player")
        )

    def _ha_control_timeout(self) -> float:
        return float(
            self._cfg.get("music", {}).get("control_timeout_s", HA_CONTROL_TIMEOUT_S)
        )

    async def _media_control(self, service: str) -> HaCallResult:
        entity = self._music_entity()
        if not entity:
            return HaCallResult.failure("not_configured")
        ha = HomeAssistantClient(self._cfg.get("ha", {}))
        return await ha.call_service(
            service,
            entity_id=entity,
            timeout_s=self._ha_control_timeout(),
        )

    async def _pause_music_playback(self) -> HaCallResult:
        return await self._media_control("media_player.media_pause")

    async def _resume_music_playback(self) -> HaCallResult:
        return await self._media_control("media_player.media_play")

    async def _handle_global_next(self) -> PipelineResult:
        if not self._music_entity():
            return await self._finish("Non ho un player musicale configurato.", listen_again=False)
        result = await self._media_control("media_player.media_next_track")
        if result.ok:
            return await self._finish("Ok, prossimo brano.", listen_again=False)
        return await self._finish(
            ha_action_error("passare al brano successivo", result),
            listen_again=False,
        )

    async def _handle_global_previous(self) -> PipelineResult:
        if not self._music_entity():
            return await self._finish("Non ho un player musicale configurato.", listen_again=False)
        result = await self._media_control("media_player.media_previous_track")
        if result.ok:
            return await self._finish("Ok, brano precedente.", listen_again=False)
        return await self._finish(
            ha_action_error("tornare al brano precedente", result),
            listen_again=False,
        )

    async def _handle_global_pause(self) -> PipelineResult:
        await self._abort_playback_if_any()
        self._playback_paused = True
        pause_result = await self._pause_music_playback()
        if pause_result.ok:
            return await self._finish("Ok, in pausa.", listen_again=False)
        if self._last_pcm:
            return await self._finish("Ok, in pausa.", listen_again=False)
        if not self._music_entity():
            return await self._finish("Non ho un player musicale configurato.", listen_again=False)
        return await self._finish(
            ha_action_error("mettere in pausa", pause_result),
            listen_again=False,
        )

    async def _handle_global_resume(self) -> PipelineResult:
        self._playback_paused = False
        resume_result = await self._resume_music_playback()
        if resume_result.ok:
            return await self._finish("Ok, riprendo.", listen_again=False)
        if self._last_pcm:
            return PipelineResult(self._last_pcm, listen_again=False)
        if not self._music_entity():
            return await self._finish("Non c'è nulla da riprendere.", listen_again=False)
        if resume_result.error:
            return await self._finish(
                ha_action_error("riprendere la musica", resume_result),
                listen_again=False,
            )
        return await self._finish("Non c'è nulla da riprendere.", listen_again=False)

    async def _handle_global_repeat(self) -> PipelineResult:
        if self._last_music_intent:
            response_it = await self.skills.execute(self._last_music_intent)
            self._last_spoken = response_it
            pcm = await asyncio.to_thread(self._synthesize_phrase, response_it)
            self._last_pcm = pcm
            self._playback_paused = False
            return PipelineResult(pcm, listen_again=False)
        if self._last_pcm:
            self._playback_paused = False
            return PipelineResult(self._last_pcm, listen_again=False)
        if self._last_spoken:
            return await self._finish(self._last_spoken, listen_again=False)
        return await self._finish("Non ho niente da ripetere.", listen_again=False)

    async def _handle_global_stop(self) -> PipelineResult:
        await self._abort_playback_if_any()
        self._playback_paused = False
        stopped: list[str] = []
        errors: list[str] = []

        ring = self._cfg.get("ring_controller")
        if ring and getattr(ring, "is_active", False):
            await ring.dismiss()
            stopped.append("l'allarme")

        if self._music_entity():
            stop_result = await self._stop_music_playback()
            if stop_result.ok:
                stopped.append("la musica")
            elif stop_result.error:
                errors.append(ha_action_error("fermare la musica", stop_result))

        if stopped and not errors:
            msg = "Ok, ho fermato " + " e ".join(stopped) + "."
        elif stopped and errors:
            msg = "Ho fermato " + " e ".join(stopped) + ". " + errors[0]
        elif errors:
            msg = errors[0]
        else:
            msg = "Ok!"
        return await self._finish(msg, listen_again=False)

    async def _stop_music_playback(self) -> HaCallResult:
        return await self._media_control("media_player.media_stop")

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
        for wake in (
            "hey jarvis", "hi jarvis", "jarvis",
            "hey kira", "ehi kira", "hey karen", "ehi karen", "karen", "kira",
        ):
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
        if is_global_stop_phrase(text):
            return False
        if is_global_pause_phrase(text) or is_global_resume_phrase(text):
            return False
        if is_global_repeat_phrase(text):
            return False
        if is_global_next_phrase(text) or is_global_previous_phrase(text):
            return False
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
        if any(token in collapsed for token in (
            "orisono", "oresono", "orasono", "orisuno", "orizzono",
            "orae sono", "cheoresono",
        )):
            return True
        if re.search(r"\b(?:chi|che|ch)\s*o?\s*(?:ne|re)?\s*sono\b", t):
            return True
        if re.search(r"\bsono\s+le\s+\d", t):
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

        weather = parse_weather_intent(text)
        if weather is not None:
            return weather

        rule = match_rule_intent(text)
        if rule is not None:
            return rule

        if any(p in t for p in ("calendario", "agenda", "appuntament")):
            when = "tomorrow" if "domani" in t else "today"
            return {**self._intent("calendar_query"), "parameters": {"when": when}}

        greetings = ("ciao", "salve", "buongiorno", "buonasera", "come stai")
        if t in greetings:
            return {
                **self._intent("general"),
                "response_it": assistant_greeting(self._cfg),
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
            recovered = recover_intent_from_llm_data({"note": raw}, text_it)
            if recovered:
                return recovered
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
            recovered = recover_intent_from_llm_data({"note": raw}, text_it)
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

        if not data.get("intent"):
            log.warning("Intent mancante dopo LLM: %s | testo=%r", data, text_it)
            recovered = recover_intent_from_llm_data(data, text_it)
            if recovered:
                return recovered
            recovered = self._recover_recipe_from_llm_data(data, text_it)
            if recovered:
                return recovered
            normalized = self._normalize_llm_intent(data, text_it)
            if normalized.get("intent"):
                return normalized
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
        if intent in ("unknown", "general"):
            if text_it:
                fb = match_rule_intent(text_it)
                if fb:
                    return fb
            normalized = self._normalize_llm_intent(data, text_it)
            if normalized.get("intent"):
                return normalized

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

        command = str(data.get("command", "")).lower()
        device = str(data.get("device", "")).lower()
        if command in ("turn_off", "remove", "delete", "cancel", "disable") and (
            "alarm" in device or "svegl" in t
        ):
            return {
                **self._intent("alarm"),
                "parameters": {
                    "action": "cancel",
                    "all": "tutt" in t or str(data.get("location", "")).lower() == "all",
                },
            }

        recovered = recover_intent_from_llm_data(data, text_it)
        if recovered:
            return recovered

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
