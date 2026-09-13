#!/usr/bin/env python3
"""
Confronta Whisper vs Parakeet locale (NIM Docker) sullo stesso WAV.

Uso sul Jetson (Parakeet già avviato con setup_riva_parakeet_jetson.sh):
  python scripts/test_asr_backends.py --audio prova.wav
  python scripts/test_asr_backends.py --audio prova.wav --backends whisper,riva

WAV mono 16 kHz:
  ffmpeg -y -i input.wav -ar 16000 -ac 1 prova.wav
"""

from __future__ import annotations

import argparse
import copy
import logging
import os
import sys
import time
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOST_DIR = Path(os.environ.get("KAREN_HOST_DIR", REPO_ROOT))
sys.path.insert(0, str(HOST_DIR))

from karen.asr import WhisperASR
from karen.asr_riva import RivaASR

log = logging.getLogger(__name__)


def load_wav(path: str) -> bytes:
    with wave.open(path, "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise ValueError("Serve WAV mono 16-bit")
        if wf.getframerate() != 16000:
            raise ValueError("Serve WAV 16 kHz")
        return wf.readframes(wf.getnframes())


def base_asr_cfg() -> dict:
    import yaml

    profile = os.environ.get("KAREN_PROFILE", "jetson")
    config_dir = HOST_DIR / "config"
    if (config_dir / "base.yaml").exists():
        from karen.config_loader import load_config

        return load_config(HOST_DIR, profile=profile)["asr"]

    config_path = HOST_DIR / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"Config non trovata in {HOST_DIR}")
    with open(config_path) as f:
        return yaml.safe_load(f)["asr"]


def run_whisper(cfg: dict, pcm: bytes) -> tuple[str, float]:
    asr = WhisperASR(cfg, HOST_DIR / "models")
    asr.load()
    t0 = time.monotonic()
    text = asr.transcribe(pcm)
    return text, time.monotonic() - t0


def run_riva(cfg: dict, pcm: bytes) -> tuple[str, float]:
    riva_cfg = copy.deepcopy(cfg)
    riva_cfg["backend"] = "riva"
    riva_cfg["riva"] = dict(cfg.get("riva") or {})
    riva_cfg["riva"]["mode"] = "local_http"
    riva_cfg["riva"].setdefault(
        "http_url", "http://127.0.0.1:9000/v1/audio/transcriptions"
    )

    asr = RivaASR(riva_cfg, HOST_DIR / "models")
    asr.load()
    t0 = time.monotonic()
    text = asr.transcribe(pcm)
    return text, time.monotonic() - t0


def main() -> None:
    parser = argparse.ArgumentParser(description="Confronto ASR Whisper vs Parakeet locale")
    parser.add_argument("--audio", required=True, help="WAV mono 16 kHz")
    parser.add_argument(
        "--backends",
        default="whisper,riva",
        help="whisper, riva",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    pcm = load_wav(args.audio)
    duration_s = len(pcm) / (16000 * 2)
    print(f"Audio: {args.audio} ({duration_s:.2f} s)\n")

    cfg = base_asr_cfg()
    for name in [b.strip() for b in args.backends.split(",") if b.strip()]:
        print(f"=== {name} ===")
        try:
            if name == "whisper":
                text, elapsed = run_whisper(cfg, pcm)
            elif name == "riva":
                text, elapsed = run_riva(cfg, pcm)
            else:
                print(f"  SKIP: {name!r}\n")
                continue
            print(f"  Testo ({elapsed:.2f} s): {text!r}\n")
        except Exception as e:
            print(f"  ERRORE: {e}\n")


if __name__ == "__main__":
    main()
