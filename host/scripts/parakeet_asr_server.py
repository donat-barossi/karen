#!/usr/bin/env python3
"""
Server HTTP ASR Parakeet (nano-parakeet, PyTorch GPU su Jetson).

API compatibile con Karen RivaASR / TOPGRO:
  GET  /v1/health/ready
  POST /v1/audio/transcriptions  (multipart file=audio.wav)

Uso:
  python3 scripts/parakeet_asr_server.py --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import argparse
import cgi
import io
import json
import logging
import sys
import tempfile
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

log = logging.getLogger("parakeet_asr_server")
_MODEL: Any = None
_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = "KarenParakeetASR/1.0"

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

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(wav_bytes)
                tmp_path = tmp.name
            duration_s = _wav_duration_s(wav_bytes)
            with _LOCK:
                text = _MODEL.transcribe(tmp_path)
            if not isinstance(text, str):
                text = str(text)
            log.info("ASR → %r (%.2f s)", text, duration_s)
            self._send_json(200, {"text": text.strip()})
        except Exception as e:
            log.exception("ASR error")
            self._send_json(500, {"error": str(e)})
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)


def _wav_duration_s(wav_bytes: bytes) -> float:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            return wf.getnframes() / float(wf.getframerate())
    except wave.Error:
        return 0.0


def _try_load(device: str, model_name: str) -> Any:
    import torch
    from nano_parakeet import from_pretrained

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA non disponibile")

    log.info("Caricamento %s su %s…", model_name, device)
    model = from_pretrained(model_name=model_name, device=device)
    if device == "cuda":
        log.info("GPU: %s", torch.cuda.get_device_name(0))
    return model


def _load_model(device: str, model_name: str) -> Any:
    if device != "auto":
        return _try_load(device, model_name)

    import torch

    if torch.cuda.is_available():
        try:
            torch.cuda.empty_cache()
            return _try_load("cuda", model_name)
        except Exception as e:
            log.warning("CUDA fallito (%s) — fallback CPU", e)
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    return _try_load("cpu", model_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Parakeet ASR HTTP server (nano-parakeet)")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--device", default="auto", choices=("auto", "cuda", "cpu"))
    parser.add_argument(
        "--model",
        default="nvidia/parakeet-tdt-0.6b-v3",
        help="HuggingFace repo del modello Parakeet TDT",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    )

    global _MODEL
    _MODEL = _load_model(args.device, args.model)
    log.info("Pronto su http://%s:%d", args.host, args.port)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Arresto")
        httpd.shutdown()


if __name__ == "__main__":
    main()
