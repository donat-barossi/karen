"""Allarme continuo (timer/sveglia) fino a dismiss vocale."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

log = logging.getLogger(__name__)

DISMISS_PHRASES = (
    "stop",
    "basta",
    "ferma",
    "kira stop",
    "hey kira stop",
    "ehi kira stop",
    "silenzio",
    "ok basta",
    "va bene",
    "ho capito",
    "si sono sveglio",
    "sono sveglio",
    "sì sono sveglio",
    "si sveglio",
    "ok sveglio",
    "sveglio",
)


def normalize_dismiss_text(text: str) -> str:
    t = text.lower().strip()
    for wake in ("hey kira", "ehi kira", "hey karen", "ehi karen", "kira", "karen"):
        t = t.replace(wake, " ")
    t = re.sub(r"[^\w\s']", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_dismiss_phrase(text: str) -> bool:
    t = normalize_dismiss_text(text)
    if not t:
        return False
    if t in ("stop", "basta", "ferma", "silenzio", "sveglio"):
        return True
    return any(p in t for p in DISMISS_PHRASES)


class RingController:
    """Suona in loop su ESP32 finché l'utente non dice stop / sono sveglio."""

    def __init__(self, cfg: dict) -> None:
        sched = cfg.get("schedule", {})
        self._interval_s = float(sched.get("ring_interval_s", 25))
        self._listen_s = float(sched.get("ring_listen_s", 5))
        self._dismiss_ack = sched.get("ring_dismiss_ack", "Ok!")
        self._transport: Any = None
        self._active = False
        self._kind = ""
        self._task: asyncio.Task | None = None
        self._dismiss_event = asyncio.Event()

    def attach_transport(self, transport: Any) -> None:
        self._transport = transport

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def dismiss_ack(self) -> str:
        return self._dismiss_ack

    async def start(self, message: str, kind: str = "timer") -> None:
        if self._active or self._transport is None:
            if self._active:
                log.debug("Ring già attivo, ignoro start (%s)", kind)
            return
        self._active = True
        self._kind = kind
        self._dismiss_event.clear()
        self._task = asyncio.create_task(self._loop(message))
        log.info("Ring avviato (%s): %s", kind, message)

    async def dismiss(self) -> None:
        if not self._active:
            return
        log.info("Ring dismiss (%s)", self._kind)
        self._active = False
        self._dismiss_event.set()

    async def _loop(self, message: str) -> None:
        assert self._transport is not None
        server = self._transport
        try:
            await server.start_ring()
            while self._active:
                play_s = await server.send_ring_audio(message)
                if not self._active or self._dismiss_event.is_set():
                    break

                listen_timeout = self._listen_s + play_s + 1.0
                try:
                    await asyncio.wait_for(self._dismiss_event.wait(), timeout=listen_timeout)
                    break
                except asyncio.TimeoutError:
                    pass

                if not self._active or self._dismiss_event.is_set():
                    break

                # Pausa tra ripetizioni, interrompibile dal dismiss
                for _ in range(int(self._interval_s * 10)):
                    if not self._active or self._dismiss_event.is_set():
                        break
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            self._active = False
            if self._transport:
                await self._transport.stop_ring()
            log.info("Ring terminato (%s)", self._kind)

    async def acknowledge_dismiss(self) -> None:
        if self._transport is None:
            return
        await self._transport.send_ring_audio(self._dismiss_ack)

    def notify_dismiss_from_asr(self, text: str) -> bool:
        if not self._active or not is_dismiss_phrase(text):
            return False
        log.info("Dismiss riconosciuto (senza wake word): %r", text)
        self._active = False
        self._dismiss_event.set()
        return True
