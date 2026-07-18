#!/usr/bin/env python3
"""
Karen – Entry point Jetson Orin Nano
Avvia il server UDP e la pipeline AI.
"""

import asyncio
import logging
import sys
import os
from pathlib import Path

import yaml

# Aggiungi la root del progetto al path
sys.path.insert(0, str(Path(__file__).parent))

from karen.pipeline import KarenPipeline
from karen.transport import AudioServer


def setup_logging(cfg: dict) -> None:
    level = getattr(logging, cfg.get("level", "INFO").upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if cfg.get("file"):
        handlers.append(logging.FileHandler(cfg["file"]))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
        handlers=handlers,
    )


def load_config(path: str = "config.yaml") -> dict:
    config_path = Path(__file__).parent / path
    if not config_path.exists():
        print(f"[ERRORE] File di configurazione non trovato: {config_path}")
        print("Copia config.yaml.example → config.yaml e modifica i valori.")
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


async def main() -> None:
    cfg = load_config()
    setup_logging(cfg.get("logging", {}))

    log = logging.getLogger("karen.main")
    log.info("=== Karen AI pipeline avvio ===")

    # Inizializza pipeline (carica modelli)
    pipeline = KarenPipeline(cfg)
    await pipeline.initialize()

    # Avvia server UDP
    transport_cfg = cfg["transport"]
    server = AudioServer(
        host=transport_cfg["listen_host"],
        port=transport_cfg["listen_port"],
        esp32_ip=transport_cfg["esp32_ip"],
        esp32_port=transport_cfg["esp32_port"],
        pipeline=pipeline,
        stream_cfg=transport_cfg.get("upload_stream"),
    )

    log.info(
        "Server UDP in ascolto su %s:%d",
        transport_cfg["listen_host"],
        transport_cfg["listen_port"],
    )

    try:
        await server.serve_forever()
    except KeyboardInterrupt:
        log.info("Arresto in corso…")
    finally:
        await pipeline.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
