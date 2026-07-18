#!/usr/bin/env python3
"""
Karen – Entry point pipeline AI (Jetson / TOPGRO / altri host)
Avvia il server UDP e la pipeline ASR → LLM → TTS.
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from karen.config_loader import load_config
from karen.scheduling import RingController
from karen.pipeline import KarenPipeline
from karen.transport import AudioServer


def setup_logging(cfg: dict) -> None:
    level = getattr(logging, cfg.get("level", "INFO").upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    log_file = cfg.get("file")
    if log_file:
        log_path = Path(log_file)
        if not log_path.is_absolute():
            log_path = Path(__file__).parent / log_path
        handlers.append(logging.FileHandler(log_path))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
        handlers=handlers,
    )


async def main() -> None:
    host_dir = Path(__file__).parent
    cfg = load_config(host_dir)
    setup_logging(cfg.get("logging", {}))

    log = logging.getLogger("karen.main")
    log.info("=== Karen AI pipeline avvio (profilo: %s) ===", cfg.get("platform"))

    pipeline = KarenPipeline(cfg)
    await pipeline.initialize()

    transport_cfg = cfg["transport"]
    server = AudioServer(
        host=transport_cfg["listen_host"],
        port=transport_cfg["listen_port"],
        esp32_ip=transport_cfg["esp32_ip"],
        esp32_port=transport_cfg["esp32_port"],
        pipeline=pipeline,
        stream_cfg=transport_cfg.get("upload_stream"),
    )

    ring = RingController(cfg)
    ring.attach_transport(server)
    server.set_ring_controller(ring)
    pipeline.set_ring_controller(ring)

    async def voice_announce(message: str) -> None:
        pcm = await asyncio.to_thread(pipeline._synthesize_phrase, message)
        await server.send_audio(pcm)

    pipeline.set_voice_announce(voice_announce)

    log.info(
        "Server UDP in ascolto su %s:%d → ESP32 %s:%d",
        transport_cfg["listen_host"],
        transport_cfg["listen_port"],
        transport_cfg["esp32_ip"],
        transport_cfg["esp32_port"],
    )

    try:
        await server.serve_forever()
    except KeyboardInterrupt:
        log.info("Arresto in corso…")
    finally:
        await pipeline.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
