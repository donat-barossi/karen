"""Utilità audio PCM 16-bit mono."""

from __future__ import annotations

import audioop
import logging

import numpy as np

log = logging.getLogger(__name__)


def resample_pcm16(pcm: bytes, from_rate: int, to_rate: int) -> bytes:
    """Resample PCM 16-bit mono (audioop — compatibile Jetson senza scipy/numpy2)."""
    if from_rate == to_rate or not pcm:
        return pcm
    converted, _ = audioop.ratecv(pcm, 2, 1, from_rate, to_rate, None)
    return converted


def normalize_pcm16(pcm: bytes, target_peak: float = 0.9) -> bytes:
    """Normalizza il picco per evitare clipping o volume troppo basso."""
    if not pcm:
        return pcm
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    peak = float(np.max(np.abs(samples)))
    if peak < 100:
        return pcm
    scale = (32767.0 * target_peak) / peak
    if scale >= 1.0:
        return pcm
    out = np.clip(samples * scale, -32768, 32767).astype(np.int16)
    return out.tobytes()
