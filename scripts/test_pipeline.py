#!/usr/bin/env python3
"""
Karen – Test Pipeline Jetson
Permette di testare la pipeline senza ESP32.

Uso:
    python test_pipeline.py --text "what time is it"
    python test_pipeline.py --text "set a timer for 3 minutes"
    python test_pipeline.py --text "turn on the kitchen lights"
    python test_pipeline.py --audio path/to/audio.wav
    python test_pipeline.py --interactive
"""

import argparse
import asyncio
import logging
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "jetson"))

import yaml
from karen.pipeline import KarenPipeline


def load_config() -> dict:
    cfg_path = Path(__file__).parent.parent / "jetson" / "config.yaml"
    if not cfg_path.exists():
        print(f"[ERRORE] {cfg_path} non trovato. Esegui prima il setup.")
        sys.exit(1)
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def text_to_fake_audio(text: str) -> bytes:
    """Crea audio finto (silenzio) – la pipeline riceverà il testo via mock."""
    samples = np.zeros(16000, dtype=np.int16)  # 1 secondo di silenzio
    return samples.tobytes()


def load_wav(path: str) -> bytes:
    """Legge WAV e restituisce PCM 16-bit mono 16kHz."""
    with wave.open(path, "rb") as wf:
        if wf.getnchannels() != 1:
            raise ValueError("Solo audio mono supportato")
        if wf.getframerate() != 16000:
            raise ValueError("Solo 16kHz supportato (resample prima con ffmpeg)")
        frames = wf.readframes(wf.getnframes())
    return frames


async def test_text(pipeline: KarenPipeline, text_en: str) -> None:
    """Testa la pipeline iniettando direttamente il testo (bypass ASR)."""
    print(f"\n[INPUT EN] {text_en}")

    # Bypass ASR: inietta il testo direttamente nell'LLM
    raw_response = pipeline.llm.generate(text_en)
    print(f"[LLM RAW] {raw_response}")

    intent_data = pipeline._parse_intent(raw_response)
    print(f"[INTENT]  {intent_data}")

    response_it = await pipeline.skills.execute(intent_data)
    print(f"[RISPOSTA IT] {response_it}")

    audio_out = pipeline.tts.synthesize(response_it)
    print(f"[TTS] {len(audio_out)} byte ({len(audio_out)//(22050*2):.1f} s)")

    # Salva risposta audio
    out_path = "/tmp/karen_response.wav"
    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(pipeline.tts.sample_rate)
        wf.writeframes(audio_out)
    print(f"[AUDIO] Salvato in {out_path}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Karen pipeline test")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Testo in inglese da processare (bypass ASR)")
    group.add_argument("--audio", help="File WAV da processare (16kHz mono PCM)")
    group.add_argument("--interactive", action="store_true",
                       help="Modalità interattiva da terminale")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s – %(message)s")

    cfg = load_config()
    pipeline = KarenPipeline(cfg)
    print("Caricamento modelli…")
    await pipeline.initialize()
    print("Pipeline pronta!\n")

    if args.text:
        await test_text(pipeline, args.text)

    elif args.audio:
        pcm = load_wav(args.audio)
        print(f"[AUDIO IN] {args.audio} – {len(pcm)} byte")
        response_pcm = await pipeline.process(pcm)
        out_path = "/tmp/karen_response.wav"
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(pipeline.tts.sample_rate)
            wf.writeframes(response_pcm)
        print(f"[AUDIO OUT] {out_path}")

    elif args.interactive:
        print("Modalità interattiva (CTRL+C per uscire)")
        print("Inserisci un comando in inglese (testo, bypass ASR):\n")
        while True:
            try:
                text = input("> ").strip()
                if text:
                    await test_text(pipeline, text)
            except KeyboardInterrupt:
                print("\nUscita.")
                break

    await pipeline.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
