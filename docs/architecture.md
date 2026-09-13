# Architettura Jarvis

Assistente vocale offline: codice `karen`, nome utente **Jarvis**, wake word **«Jarvis»**.

## Diagramma a blocchi

```
┌─────────────────────────────────────────────────────────────────────┐
│                        RETE LOCALE (Wi-Fi)                          │
│                                                                     │
│  ┌──────────────────────┐          ┌────────────────────────────┐   │
│  │  ESP32-S3 Waveshare    │          │   TOPGRO / Jetson (host/)  │   │
│  │  ES7210 mic + ES8311   │          │                            │   │
│  │  WakeNet «Jarvis»      │  UDP     │  faster-whisper (IT)       │   │
│  │  VAD + TX queue        │─────────►│  llama-cpp Phi-3 Mini      │   │
│  │  Streaming playback    │◄─────────│  Piper TTS (Giorgio)       │   │
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
   │      stream UDP da host
   └──────────────────────────► IDLE
```

Supervisor con timeout automatici su LISTENING, WAITING, SPEAKING e recovery wake AFE dopo TTS.

## Protocollo UDP (KARN)

| Direzione | Porta | Formato payload |
|-----------|-------|-----------------|
| ESP32 → host | 7001 | PCM 16 kHz, 16-bit mono, chunk 512 campioni |
| host → ESP32 | 7002 | PCM 16 kHz, 16-bit mono (TTS resample) |

### Header (8 byte)

```
[0..3]  magic   : 0x4B41524E ("KARN")
[4]     type    : 0x01 audio, 0x02 end_audio,
                  0x03 response, 0x04 end_response, 0x05 error,
                  0x08 listen_again, 0x0A log (ESP → host)
[5]     reserved: 0x00
[6..7]  seq     : uint16 big-endian
```

### Streaming

- **Upload ESP→host:** coda TX; host accumula e può chiudere con VAD (~800 ms silenzio) prima di `END`.
- **Download host→ESP:** invio in tempo reale; ESP riproduce su I2S man mano che arrivano i pacchetti.
- **Log ESP:** pacchetti `PKT_TYPE_LOG` → `host/esp32.log` (solo se Karen in ascolto).

## Pipeline host

| Step | Modello | TOPGRO (GTX 1650) | Jetson (Orin 8GB) |
|------|---------|-------------------|-------------------|
| ASR | Whisper small | GPU float16 | CPU float32 |
| LLM | Phi-3 mini Q4 | GPU | GPU |
| Skills | Python async | CPU | CPU |
| TTS | Piper Giorgio | CPU | CPU |
| **Totale** | | **~2–8 s** | **~10–20 s** |

Fast-path per comandi frequenti (ora, data, meteo, sveglie, timer) bypassa l'LLM.

Routing ibrido: regole → LLM → riconciliazione (`intent_router.py`).

## Formato intent LLM (JSON)

```json
{
  "intent": "timer|alarm|calendar_query|weather|time|date|music|general",
  "parameters": { "action": "list", "hour": 7, "minute": 30 },
  "response_it": "Risposta breve in italiano",
  "ha_service": null,
  "ha_entity": null
}
```

Intent `alarm` — azioni: `set`, `list`, `next`, `cancel`, `skip_tomorrow`, `skip_next`.

## Servizio systemd

Karen gira come **servizio utente** (`karen-topgro.service` o `karen-jetson.service`).

| Requisito | Comando |
|-----------|---------|
| Installazione | `bash host/scripts/install_systemd.sh topgro` |
| Avvio al boot | `sudo loginctl enable-linger $USER` |
| Verifica | `loginctl show-user $USER -p Linger` → `yes` |

Senza linger il servizio termina al logout SSH: l’ESP rileva «Jarvis» ma la porta 7001 non è in ascolto.

## Servizi e file chiave

| Percorso | Ruolo |
|----------|--------|
| `esp32/src/main.cpp` | Macchina a stati, VAD, wake recovery |
| `esp32/src/wake_word.cpp` | WakeNet AFE dual-mic |
| `esp32/src/config.h` | Soglia wake, gain, host IP |
| `host/karen/transport.py` | Server UDP, upload stream |
| `host/karen/pipeline.py` | ASR → LLM → skills → TTS |
| `host/karen/skills/timer_skill.py` | Timer, sveglie, parse intent |
| `host/data/schedules.json` | Sveglie e timer persistenti |
| `host/config/` | Profili jetson / topgro |

Vedi [testing-and-debug.md](testing-and-debug.md) per la procedura di debug completa.
