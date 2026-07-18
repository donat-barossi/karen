# Architettura Karen

## Diagramma a blocchi

```
┌─────────────────────────────────────────────────────────────────────┐
│                        RETE LOCALE (Wi-Fi)                          │
│                                                                     │
│  ┌──────────────────────┐          ┌────────────────────────────┐   │
│  │      ESP32-S3        │          │     Jetson Orin Nano       │   │
│  │                      │          │                            │   │
│  │  INMP441 (I2S RX)    │          │  ┌─────────────────────┐  │   │
│  │       │              │  UDP     │  │  faster-whisper      │  │   │
│  │  WakeNet9            │─────────►│  │  (small, translate)  │  │   │
│  │  "Ehi Karen"         │ PCM 16k  │  └──────────┬──────────┘  │   │
│  │       │              │          │             │ testo EN     │   │
│  │  VAD / buffer        │          │  ┌──────────▼──────────┐  │   │
│  │                      │          │  │  llama-cpp-python    │  │   │
│  │  MAX98357A (I2S TX)  │◄─────────│  │  Phi-3 Mini Q4      │  │   │
│  │  speaker             │  UDP     │  └──────────┬──────────┘  │   │
│  │                      │ PCM 22k  │             │ JSON intent  │   │
│  └──────────────────────┘          │  ┌──────────▼──────────┐  │   │
│                                    │  │   Skill Engine       │  │   │
│  ┌──────────────────────┐          │  │  timer/datetime/HA/  │  │   │
│  │  Mini PC             │          │  │  meteo/ricette       │  │   │
│  │  Home Assistant      │◄─────────│  └──────────┬──────────┘  │   │
│  │  REST API :8123      │ HTTP     │             │ testo IT     │   │
│  │                      │          │  ┌──────────▼──────────┐  │   │
│  └──────────────────────┘          │  │  Piper TTS           │  │   │
│                                    │  │  it_IT-paola-medium  │  │   │
│                                    │  └─────────────────────┘  │   │
│                                    └────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Macchina a stati ESP32

```
          wake word
  IDLE ──────────────► LISTENING
   ▲                       │
   │                  silenzio / timeout
   │                       ▼
SPEAKING ◄──────── WAITING_RESPONSE
   │      risposta UDP
   │  (fine riproduzione)
   └──────────────────────►
```

## Protocollo UDP audio

| Direzione | Porta | Formato |
|-----------|-------|---------|
| ESP32 → Jetson | 7001 | header 8B + PCM 16kHz 16-bit mono |
| Jetson → ESP32 | 7002 | header 8B + PCM 22050Hz 16-bit mono |

### Header pacchetto (8 byte)

```
[0..3]  magic   : 0x4B41524E  ("KARN")
[4]     type    : 0x01=audio, 0x02=end_of_audio,
                  0x03=response_audio, 0x04=end_of_response,
                  0x05=error
[5]     reserved: 0x00
[6..7]  seq     : uint16_t big-endian (wrapping)
```

## Pipeline Jetson – latenze stimate

| Step | Modello | Tempo (Jetson Orin Nano) |
|------|---------|--------------------------|
| ASR  | Whisper small CUDA | ~400 ms |
| LLM  | Phi-3 mini Q4 CUDA | ~600 ms (100 token) |
| TTS  | Piper paola-medium | ~200 ms |
| **Totale** | | **~1.2 s** |

## Formato risposta LLM (JSON)

```json
{
  "intent": "timer|alarm|ha_action|weather|time|date|recipe|general",
  "parameters": { "duration_s": 300 },
  "response_it": "Timer di 5 minuti avviato!",
  "ha_service": "timer.start",
  "ha_entity": null
}
```
