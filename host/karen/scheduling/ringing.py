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
    """Allarme sonoro su ESP32 (beeps locali) finché l'utente non dice stop."""

    def __init__(self, cfg: dict) -> None:
        sched = cfg.get("schedule", {})
        self._listen_poll_s = float(sched.get("ring_listen_poll_s", 0.5))
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
        del message  # annuncio vocale = beep ESP; HA gestito dal scheduler
        if self._active or self._transport is None:
            if self._active:
                log.debug("Ring già attivo, ignoro start (%s)", kind)
            return
        self._active = True
        self._kind = kind
        self._dismiss_event.clear()
        self._task = asyncio.create_task(self._loop())
        log.info("Allarme avviato (%s) → ESP beep immediato", kind)

    async def dismiss(self) -> None:
        if not self._active:
            return
        log.info("Ring dismiss (%s)", self._kind)
        self._active = False
        self._dismiss_event.set()

    async def _loop(self) -> None:
        assert self._transport is not None
        server = self._transport
        dismissed = False
        try:
            await server.start_ring()
            while self._active:
                try:
                    await asyncio.wait_for(
                        self._dismiss_event.wait(),
                        timeout=self._listen_poll_s,
                    )
                    dismissed = True
                    break
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:
            pass
        finally:
            self._active = False
            await server.stop_ring()
            if dismissed:
                await server.send_ring_audio(self._dismiss_ack)
            log.info("Ring terminato (%s)", self._kind)

    def notify_dismiss_from_asr(self, text: str) -> bool:
        if not self._active or not is_dismiss_phrase(text):
            return False
        log.info("Dismiss riconosciuto (senza wake word): %r", text)
        self._active = False
        self._dismiss_event.set()
        return True
