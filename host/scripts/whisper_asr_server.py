#!/usr/bin/env python3
"""
Server HTTP ASR (Whisper) compatibile con RivaASR / Parakeet NIM.

Espone:
  GET  /v1/health/ready
  POST /v1/audio/transcriptions  (multipart file=audio.wav, language=it|multi)

Uso sul Jetson:
  KAREN_PROFILE=jetson python3 scripts/whisper_asr_server.py --port 9000
"""

from __future__ import annotations

import argparse
import cgi
import io
import json
import logging
import sys
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HOST_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOST_ROOT))

from karen.config_loader import load_config  # noqa: E402
from karen.asr import WhisperASR  # noqa: E402

log = logging.getLogger("whisper_asr_server")
_MODEL: WhisperASR | None = None


def _wav_to_pcm16(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        if wf.getnchannels() != 1:
            raise ValueError("solo mono supportato")
        if wf.getsampwidth() != 2:
            raise ValueError("solo PCM 16-bit supportato")
        if wf.getframerate() != 16000:
            raise ValueError("solo 16 kHz supportato")
        return wf.readframes(wf.getnframes())


class Handler(BaseHTTPRequestHandler):
    server_version = "KarenWhisperASR/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, code: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.rstrip("/") in ("/v1/health/ready", "/health"):
            if _MODEL is not None:
                self._send_json(200, {"status": "ready"})
            else:
                self._send_json(503, {"status": "loading"})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/audio/transcriptions":
            self.send_error(404)
            return
        if _MODEL is None:
            self._send_json(503, {"error": "model not loaded"})
            return

        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self.send_error(400, "multipart/form-data required")
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        environ = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": ctype,
            "CONTENT_LENGTH": str(length),
        }
        fs = cgi.FieldStorage(fp=io.BytesIO(body), environ=environ, keep_blank_values=True)
        if "file" not in fs:
            self.send_error(400, "missing file field")
            return

        file_item = fs["file"]
        wav_bytes = file_item.file.read() if hasattr(file_item, "file") else file_item.value
        if isinstance(wav_bytes, str):
            wav_bytes = wav_bytes.encode()

        try:
            pcm = _wav_to_pcm16(wav_bytes)
            text = _MODEL.transcribe(pcm)
            log.info("ASR → %r (%.2f s)", text, len(pcm) / (16000 * 2))
            self._send_json(200, {"text": text})
        except Exception as e:
            log.exception("ASR error")
            self._send_json(500, {"error": str(e)})


def main() -> None:
    parser = argparse.ArgumentParser(description="Whisper ASR HTTP server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--profile", default="jetson")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    )

    global _MODEL
    cfg = load_config(HOST_ROOT, profile=args.profile)
    models_dir = HOST_ROOT / "models"
    _MODEL = WhisperASR(cfg["asr"], models_dir)
    log.info("Caricamento Whisper (%s)…", cfg["asr"].get("compute_type", "float32"))
    _MODEL.load()
    log.info("Pronto su http://%s:%d", args.host, args.port)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Arresto")
        httpd.shutdown()


if __name__ == "__main__":
    main()
