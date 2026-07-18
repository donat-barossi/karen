"""
Karen – Transport Layer
Server UDP che:
  1. Riceve chunk audio PCM dall'ESP32 in streaming (porta 7001)
  2. VAD lato host e avvia la pipeline
  3. Manda la risposta audio all'ESP32 in tempo reale (porta 7002)
"""

from __future__ import annotations

import asyncio
import audioop
import logging
import struct
import time
from typing import TYPE_CHECKING, Any

from .pipeline import ESP32_SAMPLE_RATE
from .audio_util import normalize_pcm16, resample_pcm16

if TYPE_CHECKING:
    from .pipeline import KarenPipeline

log = logging.getLogger(__name__)

# Protocollo KARN
MAGIC = 0x4B41524E  # "KARN"
PKT_AUDIO = 0x01
PKT_END_AUDIO = 0x02
PKT_RESPONSE = 0x03
PKT_END_RESPONSE = 0x04
PKT_ERROR = 0x05
PKT_START_RING = 0x06
PKT_STOP_RING = 0x07

HEADER_SIZE = 8  # magic(4) + type(1) + reserved(1) + seq(2)


def _make_header(pkt_type: int, seq: int) -> bytes:
    return struct.pack(">IBBh", MAGIC, pkt_type, 0, seq)


def _pcm_rms(pcm: bytes) -> int:
    if len(pcm) < 2:
        return 0
    return audioop.rms(pcm, 2)


class UploadStream:
    """Sessione di upload audio in streaming da ESP32."""

    __slots__ = (
        "addr",
        "buffer",
        "active",
        "finalized",
        "had_speech",
        "silence_started",
        "bytes_logged",
    )

    def __init__(self, addr: tuple[str, int]) -> None:
        self.addr = addr
        self.buffer = bytearray()
        self.active = True
        self.finalized = False
        self.had_speech = False
        self.silence_started: float | None = None
        self.bytes_logged = 0

    def append(self, payload: bytes, vad_threshold: int) -> None:
        self.buffer.extend(payload)
        rms = _pcm_rms(payload)
        now = time.monotonic()
        if rms >= vad_threshold:
            self.had_speech = True
            self.silence_started = None
        elif self.had_speech and self.silence_started is None:
            self.silence_started = now

        total = len(self.buffer)
        if total - self.bytes_logged >= ESP32_SAMPLE_RATE * 2:
            self.bytes_logged = total
            log.info(
                "Upload stream: %.1f s ricevuti da %s",
                total / (ESP32_SAMPLE_RATE * 2),
                self.addr,
            )

    def silence_ms(self) -> float:
        if self.silence_started is None:
            return 0.0
        return (time.monotonic() - self.silence_started) * 1000.0

    def duration_s(self) -> float:
        return len(self.buffer) / (ESP32_SAMPLE_RATE * 2)

    def take_audio(self) -> bytes:
        self.finalized = True
        self.active = False
        return bytes(self.buffer)


class AudioServerProtocol(asyncio.DatagramProtocol):
    """asyncio UDP protocol handler."""

    def __init__(self, server: "AudioServer") -> None:
        self._server = server
        self._transport: asyncio.BaseTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport
        log.info("UDP socket pronto")

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if len(data) < HEADER_SIZE:
            return
        magic, pkt_type, _reserved, seq = struct.unpack(">IBBh", data[:HEADER_SIZE])
        if magic != MAGIC:
            log.warning("Pacchetto con magic errato da %s", addr)
            return

        payload = data[HEADER_SIZE:]
        asyncio.ensure_future(self._server.handle_packet(pkt_type, seq, payload, addr))

    def error_received(self, exc: Exception) -> None:
        log.error("Errore UDP: %s", exc)


class AudioServer:
    def __init__(
        self,
        host: str,
        port: int,
        esp32_ip: str,
        esp32_port: int,
        pipeline: "KarenPipeline",
        stream_cfg: dict | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._esp32_addr = (esp32_ip, esp32_port)
        self._reply_addr: tuple[str, int] | None = None
        self._pipeline = pipeline

        cfg = stream_cfg or {}
        self._vad_threshold = int(cfg.get("vad_threshold", 300))
        self._vad_silence_ms = int(cfg.get("vad_silence_ms", 700))
        self._min_duration_s = float(cfg.get("min_duration_s", 0.5))

        self._stream: UploadStream | None = None
        self._transport: asyncio.DatagramTransport | None = None
        self._stream_lock = asyncio.Lock()
        self._process_lock = asyncio.Lock()
        self._ring_mode = False
        self._ring_controller: Any = None

    def set_ring_controller(self, ring: Any) -> None:
        self._ring_controller = ring

    async def start_ring(self) -> None:
        self._ring_mode = True
        await self._send_control(PKT_START_RING)
        log.info("Modalità ring avviata → ESP32")

    async def stop_ring(self) -> None:
        self._ring_mode = False
        await self._send_control(PKT_STOP_RING)
        log.info("Modalità ring fermata → ESP32")

    async def send_ring_audio(self, message: str) -> float:
        pcm = await asyncio.to_thread(self._pipeline._synthesize_phrase, message)
        await self._send_audio_response(pcm)
        return len(pcm) / (2 * ESP32_SAMPLE_RATE)

    async def _send_control(self, pkt_type: int) -> None:
        if self._transport is None:
            return
        packet = _make_header(pkt_type, 0)
        self._transport.sendto(packet, self._esp32_addr)

    async def serve_forever(self) -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: AudioServerProtocol(self),
            local_addr=(self._host, self._port),
        )
        self._transport = transport  # type: ignore[assignment]
        try:
            await asyncio.Future()
        finally:
            transport.close()

    async def handle_packet(
        self, pkt_type: int, seq: int, payload: bytes, addr: tuple[str, int]
    ) -> None:
        async with self._stream_lock:
            if pkt_type == PKT_AUDIO:
                if self._stream is not None and self._stream.finalized:
                    return

                if self._stream is None or not self._stream.active:
                    log.info("Inizio upload stream da %s", addr)
                    self._reply_addr = (addr[0], self._esp32_addr[1])
                    self._stream = UploadStream(addr)

                if self._stream.finalized:
                    return

                self._stream.append(payload, self._vad_threshold)

                if self._should_finalize_early(self._stream):
                    audio = self._stream.take_audio()
                    log.info(
                        "Upload stream chiuso (VAD Jetson): %.1f s, %d byte",
                        len(audio) / (ESP32_SAMPLE_RATE * 2),
                        len(audio),
                    )
                    if self._ring_mode:
                        asyncio.ensure_future(self._process_ring_upload(audio))
                    else:
                        asyncio.ensure_future(self._process_and_respond(audio))

            elif pkt_type == PKT_END_AUDIO:
                if self._stream is None:
                    return
                if self._stream.finalized:
                    self._stream = None
                    log.debug("END ricevuto dopo chiusura anticipata VAD")
                    return
                audio = self._stream.take_audio()
                self._stream = None
                log.info(
                    "Upload stream chiuso (END): %.1f s, %d byte",
                    len(audio) / (ESP32_SAMPLE_RATE * 2),
                    len(audio),
                )
                if self._ring_mode:
                    asyncio.ensure_future(self._process_ring_upload(audio))
                else:
                    asyncio.ensure_future(self._process_and_respond(audio))

    def _should_finalize_early(self, stream: UploadStream) -> bool:
        if self._vad_silence_ms <= 0:
            return False
        if not stream.had_speech:
            return False
        if stream.duration_s() < self._min_duration_s:
            return False
        return stream.silence_ms() >= self._vad_silence_ms

    async def send_audio(self, audio_pcm16: bytes) -> None:
        """Invia audio TTS all'ESP32 (es. conferma singola)."""
        await self._send_audio_response(audio_pcm16)

    async def _process_ring_upload(self, audio_pcm16: bytes) -> None:
        if not audio_pcm16 or not self._ring_controller:
            return
        text = await self._pipeline.transcribe_only(audio_pcm16)
        if not text:
            return
        log.info("Ring listen ASR → '%s'", text)
        if self._ring_controller.notify_dismiss_from_asr(text):
            await self._transport.send_ring_audio(self._ring_controller.dismiss_ack)

    async def _process_and_respond(self, audio_pcm16: bytes) -> None:
        if not audio_pcm16:
            log.warning("Upload stream vuoto, ignorato")
            return

        async with self._process_lock:
            try:
                response_pcm = await self._pipeline.process(audio_pcm16)
            except Exception as e:
                log.exception("Errore pipeline: %s", e)
                response_pcm = self._pipeline.tts.synthesize(
                    "Mi dispiace, si è verificato un errore."
                )
                response_pcm = normalize_pcm16(
                    resample_pcm16(
                        response_pcm,
                        self._pipeline.tts.sample_rate,
                        ESP32_SAMPLE_RATE,
                    )
                )

            await self._send_audio_response(response_pcm)

    async def _send_audio_response(self, audio_pcm16: bytes) -> None:
        if self._transport is None:
            return

        dest = self._reply_addr or self._esp32_addr
        chunk_samples = 512
        chunk_bytes = chunk_samples * 2
        seq = 0
        chunk_duration_s = chunk_samples / ESP32_SAMPLE_RATE

        for offset in range(0, len(audio_pcm16), chunk_bytes):
            chunk = audio_pcm16[offset : offset + chunk_bytes]
            is_last = (offset + chunk_bytes) >= len(audio_pcm16)
            pkt_type = PKT_END_RESPONSE if is_last else PKT_RESPONSE
            packet = _make_header(pkt_type, seq) + chunk
            self._transport.sendto(packet, dest)
            seq = (seq + 1) & 0x7FFF
            await asyncio.sleep(chunk_duration_s)

        duration_s = len(audio_pcm16) / (2 * ESP32_SAMPLE_RATE)
        log.info(
            "Risposta audio inviata a %s: %d byte (%.1f s @ %d Hz)",
            dest,
            len(audio_pcm16),
            duration_s,
            ESP32_SAMPLE_RATE,
        )
