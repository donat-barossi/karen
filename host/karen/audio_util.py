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


def trim_silence_pcm16(
    pcm: bytes,
    sample_rate: int = 16000,
    frame_ms: int = 20,
    threshold: int = 350,
    padding_ms: int = 250,
) -> bytes:
    """Taglia silenzio iniziale/finale per ASR più veloce su registrazioni lunghe."""
    if len(pcm) < 4:
        return pcm

    frame_bytes = max(2, (sample_rate * frame_ms // 1000) * 2)
    pad_bytes = (sample_rate * padding_ms // 1000) * 2
    n_frames = len(pcm) // frame_bytes
    if n_frames < 2:
        return pcm

    first = 0
    for i in range(n_frames):
        chunk = pcm[i * frame_bytes : (i + 1) * frame_bytes]
        if audioop.rms(chunk, 2) >= threshold:
            first = i
            break

    last = n_frames - 1
    for i in range(n_frames - 1, first - 1, -1):
        chunk = pcm[i * frame_bytes : (i + 1) * frame_bytes]
        if audioop.rms(chunk, 2) >= threshold:
            last = i
            break

    start = max(0, first * frame_bytes - pad_bytes)
    end = min(len(pcm), (last + 1) * frame_bytes + pad_bytes)
    trimmed = pcm[start:end]

    if len(trimmed) < len(pcm):
        log.debug(
            "Audio trim: %.2f s → %.2f s",
            len(pcm) / (sample_rate * 2),
            len(trimmed) / (sample_rate * 2),
        )
    return trimmed
