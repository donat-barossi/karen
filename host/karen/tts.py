"""
Karen – TTS Engine
Usa Piper (piper-tts) con voce italiana paola-medium.
Output: PCM 16-bit mono al sample rate del modello (22050 Hz).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class PiperTTS:
    def __init__(self, cfg: dict, models_dir: Path) -> None:
        self._cfg = cfg

        model_path = cfg["model_path"]
        config_path = cfg.get("config_path", model_path + ".json")

        self._model_path = str(models_dir / model_path) \
            if not Path(model_path).is_absolute() else model_path
        self._config_path = str(models_dir / config_path) \
            if not Path(config_path).is_absolute() else config_path

        self._voice: Any = None
        self._sample_rate: int = cfg.get("sample_rate", 22050)

    def load(self) -> None:
        from piper.voice import PiperVoice

        use_cuda = bool(self._cfg.get("use_cuda", False))
        self._voice = PiperVoice.load(
            self._model_path,
            config_path=self._config_path,
            use_cuda=use_cuda,
        )
        # Recupera il sample rate dal modello
        self._sample_rate = self._voice.config.sample_rate
        log.debug("Piper caricato: %s  sample_rate=%d",
                  self._model_path, self._sample_rate)

    def synthesize(self, text_it: str) -> bytes:
        """
        Sintetizza testo italiano in audio PCM 16-bit.

        Args:
            text_it: testo in italiano da sintetizzare

        Returns:
            buffer bytes con campioni PCM 16-bit LE mono
        """
        if self._voice is None:
            raise RuntimeError("Piper non caricato. Chiama load() prima.")

        from piper.config import SynthesisConfig

        syn_cfg = SynthesisConfig(
            length_scale=self._cfg.get("length_scale", 1.0),
        )

        # Raccoglie i chunk PCM int16 restituiti da synthesize()
        pcm_chunks: list[bytes] = []
        for chunk in self._voice.synthesize(text_it, syn_config=syn_cfg):
            pcm_chunks.append(chunk.audio_int16_bytes)

        return b"".join(pcm_chunks)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate
