# Architettura Karen

## Diagramma a blocchi

```
┌─────────────────────────────────────────────────────────────────────┐
│                        RETE LOCALE (Wi-Fi)                          │
│                                                                     │
│  ┌──────────────────────┐          ┌────────────────────────────┐   │
│  │  ESP32-S3 Waveshare    │          │   TOPGRO / Jetson (host/)  │   │
│  │  ES7210 mic + ES8311   │          │                            │   │
│  │  WakeNet "Hey Kira"    │  UDP     │  faster-whisper (IT)       │   │
│  │  VAD + TX queue        │─────────►│  llama-cpp Phi-3 Mini      │   │
│  │  Streaming playback    │◄─────────│  Piper TTS + skills        │   │
│  └──────────────────────┘  7001/7002└─────────────┬──────────────┘   │
│                                                    │ HTTP             │
│  ┌──────────────────────┐                         ▼                  │
│  │  Mini PC             │          Home Assistant REST :8123          │
│  │  Home Assistant      │◄───────────────────────────────────────────│
│  └──────────────────────┘                                          │
└─────────────────────────────────────────────────────────────────────┘
```

## Macchina a stati ESP32

```
          wake word / BOOT
  IDLE ──────────────────► LISTENING
   ▲                            │
   │                       silenzio / max 8s
   │                            ▼
SPEAKING ◄────────── WAITING_RESPONSE
   │      stream UDP da Jetson
   └──────────────────────────► IDLE
```

Supervisor con timeout automatici su LISTENING, WAITING, SPEAKING.

## Protocollo UDP (KARN)

| Direzione | Porta | Formato payload |
|-----------|-------|-----------------|
| ESP32 → Jetson | 7001 | PCM 16 kHz, 16-bit mono, chunk 512 campioni |
| Jetson → ESP32 | 7002 | PCM 16 kHz, 16-bit mono (TTS resample) |

### Header (8 byte)

```
[0..3]  magic   : 0x4B41524E ("KARN")
[4]     type    : 0x01 audio, 0x02 end_audio,
                  0x03 response, 0x04 end_response, 0x05 error
[5]     reserved: 0x00
[6..7]  seq     : uint16 big-endian
```

### Streaming

- **Upload ESP→Jetson:** coda TX con pacing 32 ms/pacchetto; Jetson accumula e può chiudere con VAD (700 ms silenzio) prima di `END`.
- **Download Jetson→ESP:** invio in tempo reale; ESP riproduce su I2S man mano che arrivano i pacchetti.

## Pipeline Jetson

| Step | Modello | Device (Orin 8GB) | Tempo tipico |
|------|---------|-------------------|--------------|
| ASR | Whisper small | CPU float32 | 3–8 s |
| LLM | Phi-3 mini Q4 | GPU | 2–6 s |
| Skills | Python async | CPU | <100 ms |
| TTS | Piper paola | CPU | 1–3 s |
| **Totale** | | | **~10–20 s** |

Fast-path per comandi frequenti (ora, data, meteo, saluti) bypassa l'LLM.

## Formato intent LLM (JSON)

```json
{
  "intent": "timer|alarm|ha_action|weather|time|date|general",
  "parameters": { "duration_s": 300 },
  "response_it": "Timer di cinque minuti avviato!",
  "ha_service": "timer.start",
  "ha_entity": null
}
```

## Servizi e file chiave

| Percorso | Ruolo |
|----------|--------|
| `esp32/src/main.cpp` | Macchina a stati, VAD |
| `esp32/src/udp_transport.cpp` | TX/RX UDP, streaming playback |
| `host/karen/transport.py` | Server UDP, upload stream |
| `host/karen/pipeline.py` | ASR → LLM → skills → TTS |
| `host/config/` | Profili jetson / topgro |

Vedi [testing-and-debug.md](testing-and-debug.md) per la procedura di debug completa.
