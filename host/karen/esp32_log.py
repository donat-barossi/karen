"""Log persistenti ricevuti dall'ESP32 via UDP (PKT_TYPE_LOG)."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


class Esp32LogWriter:
    def __init__(self, path: str | None, host_dir: Path) -> None:
        self._fp = None
        if not path:
            return
        log_path = Path(path)
        if not log_path.is_absolute():
            log_path = host_dir / log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(log_path, "a", encoding="utf-8", buffering=1)
        log.info("Log ESP32 persistente: %s", log_path)

    def write(self, addr: str, message: str) -> None:
        msg = message.strip()
        if not msg:
            return
        line = f"{datetime.now().isoformat(timespec='seconds')} [{addr}] {msg}"
        log.info("ESP32: %s", msg)
        if self._fp:
            self._fp.write(line + "\n")

    def close(self) -> None:
        if self._fp:
            self._fp.close()
            self._fp = None
