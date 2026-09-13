#!/usr/bin/env python3
"""
Server HTTP ASR FastConformer Italian-only (ONNX, CPU su TOPGRO).

API compatibile con Karen RivaASR:
  GET  /v1/health/ready
  POST /v1/audio/transcriptions  (multipart file=audio.wav)

Uso:
  python3 scripts/fastconformer_asr_server.py --host 127.0.0.1 --port 9000
"""

from __future__ import annotations

import argparse
import cgi
import io
import json
import logging
import tempfile
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

log = logging.getLogger("fastconformer_asr_server")
_MODEL: Any = None
_LOCK = threading.Lock()
_DEFAULT_MODEL = "OpenVoiceOS/stt_it_fastconformer_hybrid_large_pc_onnx"


class Handler(BaseHTTPRequestHandler):
    server_version = "KarenFastConformerASR/1.0"

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
                text = _MODEL.recognize(tmp_path)
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


def _load_model(model_name: str) -> Any:
    import onnx_asr

    log.info("Caricamento %s (ONNX CPU)…", model_name)
    model = onnx_asr.load_model(model_name)
    log.info("Modello FastConformer IT pronto")
    return model


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FastConformer Italian ASR HTTP server (onnx-asr)"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help="Repo HuggingFace o path locale del modello ONNX",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    )

    global _MODEL
    _MODEL = _load_model(args.model)
    log.info("Pronto su http://%s:%d", args.host, args.port)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Arresto")
        httpd.shutdown()


if __name__ == "__main__":
    main()
