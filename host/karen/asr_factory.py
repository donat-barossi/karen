"""Factory ASR con fallback opzionale a Whisper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Protocol

from .asr import WhisperASR

log = logging.getLogger(__name__)


class ASRBackend(Protocol):
    def load(self) -> None: ...
    def transcribe(self, audio_pcm16: bytes) -> str: ...
    def transcribe_ring_dismiss(self, audio_pcm16: bytes) -> str: ...


class FallbackASR:
    """Prova backend primario (Riva); su errore usa Whisper."""

    def __init__(self, primary: ASRBackend, fallback: WhisperASR) -> None:
        self._primary = primary
        self._fallback = fallback
        self._primary_ok = False

    def load(self) -> None:
        self._fallback.load()
        try:
            self._primary.load()
            self._primary_ok = True
            log.info("ASR primario attivo (%s)", type(self._primary).__name__)
        except Exception as e:
            self._primary_ok = False
            log.warning(
                "ASR primario non disponibile — solo Whisper: %s", e
            )

    def transcribe(self, audio_pcm16: bytes) -> str:
        if self._primary_ok:
            try:
                return self._primary.transcribe(audio_pcm16)
            except Exception as e:
                log.warning("Riva ASR fallito, fallback Whisper: %s", e)
        return self._fallback.transcribe(audio_pcm16)

    def transcribe_ring_dismiss(self, audio_pcm16: bytes) -> str:
        if self._primary_ok:
            try:
                return self._primary.transcribe_ring_dismiss(audio_pcm16)
            except Exception as e:
                log.warning("Riva ring ASR fallito, fallback Whisper: %s", e)
        return self._fallback.transcribe_ring_dismiss(audio_pcm16)


def create_asr(cfg: dict[str, Any], models_dir: Path) -> ASRBackend:
    backend = (cfg.get("backend") or "whisper").lower()
    whisper = WhisperASR(cfg, models_dir)

    if backend == "whisper":
        return whisper

    if backend == "riva":
        from .asr_riva import RivaASR

        riva = RivaASR(cfg, models_dir)
        if cfg.get("riva", {}).get("fallback_whisper", True):
            return FallbackASR(riva, whisper)
        return riva

    raise ValueError(f"ASR backend sconosciuto: {backend!r}")
