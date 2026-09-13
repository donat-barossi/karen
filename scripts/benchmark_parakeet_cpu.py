#!/usr/bin/env python3
"""
Benchmark Parakeet (nano-parakeet, CPU) — Jetson vs TOPGRO.

Genera un WAV di test (Piper) se mancante, poi misura:
  - topgro-local: inferenza CPU diretta su TOPGRO
  - jetson-http:  POST verso karen-parakeet-asr (path produzione)
  - jetson-local: inferenza CPU diretta sul Jetson (via SSH, opzionale)

Uso (da repo, eseguito su TOPGRO):
  python3 scripts/benchmark_parakeet_cpu.py
  python3 scripts/benchmark_parakeet_cpu.py --audio /tmp/bench_it.wav --runs 5
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOST = Path(os.environ.get("KAREN_HOST_DIR", REPO / "host")).expanduser().resolve()
JETSON = os.environ.get("KAREN_JETSON", "donat@192.168.1.96")
JETSON_HTTP = os.environ.get(
    "PARAKEET_HTTP_URL", "http://192.168.1.96:9000/v1/audio/transcriptions"
)


def wav_duration_s(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def ensure_test_wav(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    venv_py = HOST / "venv" / "bin" / "python"
    py = str(venv_py if venv_py.exists() else sys.executable)
    script = f"""
import sys, wave
from pathlib import Path
sys.path.insert(0, {str(HOST)!r})
from karen.config_loader import load_config
from karen.tts import PiperTTS
from karen.audio_util import normalize_pcm16, resample_pcm16

host = Path({str(HOST)!r})
cfg = load_config(host, profile="topgro")
tts = PiperTTS(cfg["tts"], host / "models")
tts.load()
pcm = tts.synthesize("Che ore sono? Dimmi l'ora per favore.")
pcm = normalize_pcm16(resample_pcm16(pcm, tts.sample_rate, 16000))
out = Path({str(path)!r})
with wave.open(str(out), "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    wf.writeframes(pcm)
print(out)
"""
    subprocess.check_call([py, "-c", script])


def bench_topgro_local(wav: Path, runs: int) -> dict:
    venv_py = HOST / "venv" / "bin" / "python"
    py = str(venv_py if venv_py.exists() else sys.executable)
    script = f"""
import time, wave
from pathlib import Path
from nano_parakeet import from_pretrained

wav = Path({str(wav)!r})
with wave.open(str(wav), "rb") as wf:
    frames = wf.getnframes()
    sr = wf.getframerate()
    dur = frames / float(sr)

# warm-up
model = from_pretrained(device="cpu")
_ = model.transcribe(str(wav))

times = []
text = ""
for _ in range({runs}):
    t0 = time.perf_counter()
    text = model.transcribe(str(wav))
    times.append(time.perf_counter() - t0)

import json
print(json.dumps({{"times": times, "text": text, "duration_s": dur}}))
"""
    out = subprocess.check_output([py, "-c", script], text=True)
    data = json.loads(out.strip().splitlines()[-1])
    return _summarize("topgro-local (CPU diretto)", data["times"], data["text"], data["duration_s"])


def bench_jetson_http(wav: Path, runs: int) -> dict:
    import requests

    sys.path.insert(0, str(HOST))
    from karen.asr_riva import pcm16_to_wav

    with wave.open(str(wav), "rb") as wf:
        pcm = wf.readframes(wf.getnframes())
    dur = wav_duration_s(wav)
    payload = pcm16_to_wav(pcm)

    # warm-up
    requests.post(
        JETSON_HTTP,
        files={"file": ("bench.wav", payload, "audio/wav")},
        data={"language": "it"},
        timeout=120,
    ).raise_for_status()

    times: list[float] = []
    text = ""
    for _ in range(runs):
        t0 = time.perf_counter()
        r = requests.post(
            JETSON_HTTP,
            files={"file": ("bench.wav", payload, "audio/wav")},
            data={"language": "it"},
            timeout=120,
        )
        r.raise_for_status()
        times.append(time.perf_counter() - t0)
        text = r.json().get("text", "")

    return _summarize("jetson-http (TOPGRO→Jetson :9000)", times, text, dur)


def bench_jetson_local(wav: Path, runs: int) -> dict:
    remote_wav = "/tmp/karen_bench_parakeet.wav"
    subprocess.check_call(["scp", "-q", str(wav), f"{JETSON}:{remote_wav}"])
    remote_script = f"""import time, wave, json
from pathlib import Path
from nano_parakeet import from_pretrained

wav = Path({remote_wav!r})
with wave.open(str(wav), 'rb') as wf:
    dur = wf.getnframes() / float(wf.getframerate())

model = from_pretrained(device='cpu')
_ = model.transcribe(str(wav))

times = []
text = ''
for _ in range({runs}):
    t0 = time.perf_counter()
    text = model.transcribe(str(wav))
    times.append(time.perf_counter() - t0)

print(json.dumps({{'times': times, 'text': text, 'duration_s': dur}}))
"""
    out = subprocess.check_output(
        [
            "ssh",
            JETSON,
            "export LD_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu/openblas-pthread:/usr/local/cuda/lib64; "
            "~/karen/jetson/venv/bin/python -c "
            + repr(remote_script),
        ],
        text=True,
    )
    data = json.loads(out.strip().splitlines()[-1])
    return _summarize("jetson-local (CPU diretto ARM)", data["times"], data["text"], data["duration_s"])


def _summarize(label: str, times: list[float], text: str, audio_s: float) -> dict:
    med = statistics.median(times)
    return {
        "label": label,
        "runs": len(times),
        "median_s": round(med, 3),
        "min_s": round(min(times), 3),
        "max_s": round(max(times), 3),
        "rtf": round(audio_s / med, 2) if med > 0 else 0,
        "audio_s": round(audio_s, 2),
        "text": text.strip(),
    }


def print_row(r: dict) -> None:
    print(
        f"{r['label']:40}  "
        f"med={r['median_s']:.3f}s  "
        f"min={r['min_s']:.3f}s  "
        f"RTF={r['rtf']:.1f}x  "
        f"audio={r['audio_s']:.1f}s"
    )
    print(f"  → {r['text'][:80]!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Parakeet CPU Jetson vs TOPGRO")
    parser.add_argument("--audio", type=Path, default=Path("/tmp/karen_bench_it.wav"))
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--modes",
        default="topgro-local,jetson-http,jetson-local",
        help="comma-separated: topgro-local,jetson-http,jetson-local",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(HOST))
    ensure_test_wav(args.audio)
    dur = wav_duration_s(args.audio)
    print(f"=== Parakeet CPU benchmark ===")
    print(f"Audio: {args.audio} ({dur:.2f} s)")
    print(f"Runs per mode: {args.runs}\n")

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    results: list[dict] = []

    if "topgro-local" in modes:
        print("Caricamento nano-parakeet su TOPGRO (prima esecuzione può scaricare il modello)…")
        results.append(bench_topgro_local(args.audio, args.runs))
        print_row(results[-1])
        print()

    if "jetson-http" in modes:
        results.append(bench_jetson_http(args.audio, args.runs))
        print_row(results[-1])
        print()

    if "jetson-local" in modes:
        results.append(bench_jetson_local(args.audio, args.runs))
        print_row(results[-1])
        print()

    if len(results) >= 2:
        base = results[0]["median_s"]
        print("=== Rapporto (median, vs primo test) ===")
        for r in results:
            ratio = r["median_s"] / base if base > 0 else 0
            print(f"  {r['label']:40}  {ratio:.2f}x")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
