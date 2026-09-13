"""ASR via Parakeet NIM locale (Docker su Jetson/TOPGRO) — solo rete privata, niente cloud."""

from __future__ import annotations

import io
import logging
import wave
from typing import Any

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


def pcm16_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class RivaASR:
    """
    Parakeet multilingual via NIM Docker locale:
      - local_http: POST /v1/audio/transcriptions (consigliato)
      - local_grpc: Riva gRPC su host:50051
    """

    def __init__(self, cfg: dict[str, Any], models_dir: Any = None) -> None:
        del models_dir
        riva = cfg.get("riva") or {}
        self._mode = riva.get("mode", "local_http")
        if self._mode not in ("local_http", "local_grpc"):
            raise ValueError(
                f"Riva ASR: mode={self._mode!r} non supportato (solo locale)"
            )
        self._language_code = riva.get("language_code", "multi")
        self._http_url = riva.get(
            "http_url", "http://127.0.0.1:9000/v1/audio/transcriptions"
        )
        self._server = riva.get("server", "127.0.0.1:50051")
        self._timeout_s = float(riva.get("timeout_s", 60))
        self._asr_service: Any = None

    def load(self) -> None:
        if self._mode == "local_http":
            log.info(
                "ASR remoto (HTTP): %s lang=%s",
                self._http_url,
                self._language_code,
            )
            return

        import riva.client

        auth = riva.client.Auth(use_ssl=False, uri=self._server)
        self._asr_service = riva.client.ASRService(auth)
        log.info(
            "Parakeet ASR locale (gRPC): %s lang=%s",
            self._server,
            self._language_code,
        )

    def _recognition_config(self, *, short: bool = False) -> Any:
        import riva.client

        return riva.client.RecognitionConfig(
            language_code=self._language_code,
            max_alternatives=1,
            enable_automatic_punctuation=not short,
            verbatim_transcripts=not short,
        )

    def _transcribe_grpc(self, pcm: bytes) -> str:
        if self._asr_service is None:
            raise RuntimeError("Parakeet ASR gRPC non caricato")

        wav = pcm16_to_wav(pcm)
        config = self._recognition_config()
        response = self._asr_service.offline_recognize(wav, config)
        if not response.results:
            return ""
        return response.results[0].alternatives[0].transcript.strip()

    def _transcribe_http(self, pcm: bytes) -> str:
        import requests

        wav = pcm16_to_wav(pcm)
        files = {"file": ("audio.wav", wav, "audio/wav")}
        data = {
            "language": self._language_code,
            "response_format": "json",
        }
        resp = requests.post(
            self._http_url,
            files=files,
            data=data,
            timeout=self._timeout_s,
        )
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, dict):
            return str(body.get("text", "")).strip()
        return str(body).strip()

    def transcribe(self, audio_pcm16: bytes) -> str:
        if self._mode == "local_http":
            text = self._transcribe_http(audio_pcm16)
        else:
            text = self._transcribe_grpc(audio_pcm16)
        log.debug("Parakeet ASR → %r", text)
        return text

    def transcribe_ring_dismiss(self, audio_pcm16: bytes) -> str:
        if self._mode == "local_http":
            return self.transcribe(audio_pcm16)

        if self._asr_service is None:
            raise RuntimeError("Parakeet ASR gRPC non caricato")

        wav = pcm16_to_wav(audio_pcm16)
        config = self._recognition_config(short=True)
        response = self._asr_service.offline_recognize(wav, config)
        if not response.results:
            return ""
        return response.results[0].alternatives[0].transcript.strip()
