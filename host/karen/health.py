"""Controlli di robustezza: avvio e monitoraggio runtime."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def check_linger() -> str | None:
    """Ritorna messaggio di warning se linger non è abilitato."""
    user = os.environ.get("USER") or os.environ.get("LOGNAME")
    if not user:
        return None
    try:
        out = subprocess.run(
            ["loginctl", "show-user", user, "-p", "Linger", "--value"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if out.stdout.strip().lower() != "yes":
            return (
                f"Linger disabilitato per {user}: Jarvis si ferma al logout SSH. "
                f"Esegui: sudo loginctl enable-linger {user}"
            )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def check_models(cfg: dict[str, Any], host_dir: Path) -> list[str]:
    """Verifica presenza file modello essenziali."""
    issues: list[str] = []
    models = host_dir / "models"

    asr_path = cfg.get("asr", {}).get("model_path", "whisper-small-ct2")
    if not (models / asr_path).exists() and not Path(asr_path).is_absolute():
        issues.append(f"Modello ASR mancante: {models / asr_path}")

    llm_path = cfg.get("llm", {}).get("model_path", "")
    if llm_path and not (models / llm_path).exists():
        issues.append(f"Modello LLM mancante: {models / llm_path}")

    tts_path = cfg.get("tts", {}).get("model_path", "")
    if tts_path and not (models / tts_path).exists():
        issues.append(f"Modello TTS mancante: {models / tts_path}")

    return issues


def check_config(cfg: dict[str, Any]) -> list[str]:
    """Warning su configurazione incompleta."""
    issues: list[str] = []
    token = cfg.get("ha", {}).get("token", "")
    if not token or "YOUR_HA" in token:
        issues.append("Token Home Assistant non configurato (skill HA disabilitate).")

    esp_ip = cfg.get("transport", {}).get("esp32_ip", "")
    if not esp_ip:
        issues.append("transport.esp32_ip non impostato.")

    return issues


def run_startup_checks(cfg: dict[str, Any], host_dir: Path) -> None:
    """Logga warning/errori evidenti all'avvio."""
    warnings: list[str] = []
    linger = check_linger()
    if linger:
        warnings.append(linger)
    warnings.extend(check_models(cfg, host_dir))
    warnings.extend(check_config(cfg))

    if not warnings:
        log.info("Controlli avvio: OK")
        return

    log.warning("=== Controlli avvio: %d avviso/i ===", len(warnings))
    for msg in warnings:
        log.warning("  • %s", msg)


class RuntimeWatchdog:
    """Monitora contatto ESP e segnala silenzio prolungato."""

    def __init__(self, esp_silence_warn_s: float = 120.0) -> None:
        self._esp_silence_warn_s = esp_silence_warn_s
        self._last_esp_activity = time.monotonic()
        self._warned = False

    def note_esp_activity(self) -> None:
        self._last_esp_activity = time.monotonic()
        if self._warned:
            log.info("ESP di nuovo raggiungibile")
            self._warned = False

    def seconds_since_esp(self) -> float:
        return time.monotonic() - self._last_esp_activity

    async def run(self) -> None:
        while True:
            await _sleep(60)
            silent = self.seconds_since_esp()
            if silent >= self._esp_silence_warn_s and not self._warned:
                log.warning(
                    "ESP non invia pacchetti da %.0f s — wake word potrebbe "
                    "funzionare ma log/heartbeat assenti; verificare Wi-Fi e host attivo.",
                    silent,
                )
                self._warned = True


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
