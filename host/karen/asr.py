"""
Karen – ASR Module
Usa faster-whisper per trascrizione in italiano.
"""

from __future__ import annotations

import gc
import logging
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # Hz


class WhisperASR:
    def __init__(self, cfg: dict, models_dir: Path) -> None:
        self._cfg = cfg
        self._model_path = str(models_dir / cfg["model_path"]) \
            if not Path(cfg["model_path"]).is_absolute() \
            else cfg["model_path"]
        self._model: Any = None
        self._device = "cpu"
        self._compute_type = "float32"

    def _create_model(self, device: str, compute_type: str) -> Any:
        from faster_whisper import WhisperModel

        return WhisperModel(
            self._model_path,
            device=device,
            compute_type=compute_type,
        )

    def load(self) -> None:
        device = self._cfg.get("device", "cpu")
        compute_type = self._cfg.get("compute_type", "float32")

        if device == "cuda":
            import ctranslate2
            if ctranslate2.get_cuda_device_count() == 0:
                log.warning("CUDA non disponibile — Whisper su CPU")
                device = "cpu"
                compute_type = "float32"

        self._device = device
        self._compute_type = compute_type
        try:
            self._model = self._create_model(device, compute_type)
        except RuntimeError as e:
            msg = str(e).lower()
            if device == "cuda" and ("out of memory" in msg or "cuda failed" in msg):
                self._load_cpu_fallback()
            else:
                raise
        log.info("Whisper: device=%s compute_type=%s", self._device, self._compute_type)

    def _release_model(self) -> None:
        self._model = None
        gc.collect()

    def _load_cpu_fallback(self) -> None:
        if self._device == "cpu" and self._compute_type == "float32":
            return
        log.warning("ASR fallback → CPU/float32")
        self._release_model()
        self._device = "cpu"
        self._compute_type = "float32"
        self._model = self._create_model("cpu", "float32")

    def _transcribe_once(self, audio_pcm16: bytes) -> str:
        if self._model is None:
            raise RuntimeError("Modello ASR non caricato. Chiama load() prima.")

        audio_np = np.frombuffer(audio_pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        duration_s = len(audio_np) / SAMPLE_RATE
        log.debug("ASR input: %.2f s (%d byte)", duration_s, len(audio_pcm16))

        vad_filter = self._cfg.get("vad_filter", False)
        vad_params = self._cfg.get("vad_parameters", {"min_silence_duration_ms": 500})

        kwargs: dict[str, Any] = {
            "language": self._cfg.get("language", "it"),
            "task": self._cfg.get("task", "transcribe"),
            "beam_size": self._cfg.get("beam_size", 3),
            "vad_filter": vad_filter,
            "initial_prompt": self._cfg.get("initial_prompt"),
            "condition_on_previous_text": self._cfg.get(
                "condition_on_previous_text", False
            ),
            "temperature": self._cfg.get("temperature", 0.0),
        }
        if vad_filter:
            kwargs["vad_parameters"] = vad_params

        segments, info = self._model.transcribe(audio_np, **kwargs)

        text = " ".join(seg.text.strip() for seg in segments).strip()
        log.debug("ASR detected_language=%s, text='%s'", info.language, text)
        return text

    def transcribe(self, audio_pcm16: bytes) -> str:
        """Trascrive audio PCM 16-bit mono 16kHz in italiano."""
        try:
            return self._transcribe_once(audio_pcm16)
        except (RuntimeError, ValueError) as e:
            msg = str(e).lower()
            if "out of memory" not in msg and "cuda failed" not in msg and "int8" not in msg:
                raise
            self._load_cpu_fallback()
            return self._transcribe_once(audio_pcm16)
