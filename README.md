# Karen – Assistente Vocale Domestico Offline

Assistente vocale **offline** in italiano:

| Nodo | Hardware | Ruolo |
|------|----------|-------|
| Nodo audio | ESP32-S3 Waveshare | Wake word · mic · speaker · UDP |
| Cervello AI | Jetson Orin Nano *(→ TOPGRO)* | ASR → LLM → TTS |
| Server casa | Mini PC | Home Assistant · timer · automazioni |

---

## Flusso di una richiesta

```
[Utente: "Hey Kira" + comando in italiano]
      │
      ▼
ESP32-S3 ── registra e invia UDP in streaming (16 kHz PCM)
      │
      ▼
Jetson (porta 7001)
  ├─ Whisper small (trascrizione IT)
  ├─ Phi-3 Mini (intent JSON) o fast-path
  ├─ Skill engine (timer, HA, meteo, ora…)
  └─ Piper TTS (voce Paola → resample 16 kHz)
      │
      ▼
ESP32 (porta 7002) ── riproduzione streaming su speaker integrato
```

---

## Struttura repository

```
karen/
├── esp32/          Firmware ESP32-S3 (PlatformIO + ESP-IDF)
├── jetson/         Pipeline AI Python (ASR · LLM · TTS · skills)
├── homeassistant/  Package HA e docker-compose
├── scripts/        Setup, test e utilità
└── docs/           Architettura, cablaggio, setup, test/debug
```

---

## Quick start

### 1. ESP32-S3

```bash
cd esp32
cp src/config.h.example src/config.h   # Wi-Fi + IP Jetson
~/.karen-pio-venv/bin/pio run -t upload --upload-port /dev/ttyACM0
```

### 2. Jetson Orin Nano

```bash
cd jetson
cp config.yaml.example config.yaml
bash ../scripts/setup_jetson.sh
bash ../scripts/install_models.sh
bash scripts/install_systemd.sh      # servizio con auto-restart
```

### 3. Test senza ESP32

```bash
python3 scripts/test_pipeline.py --text "che ore sono"
python3 scripts/test_pipeline.py --audio mia_prova.wav
```

---

## Documentazione

| Documento | Contenuto |
|-----------|-----------|
| [Architettura](docs/architecture.md) | Protocollo UDP, stati ESP, pipeline |
| [Setup completo](docs/setup-guide.md) | Installazione passo-passo |
| [Test e debug](docs/testing-and-debug.md) | **Debug completo per livello** |
| [Migrazione TOPGRO](docs/topgro-migration.md) | Piano gaming PC (branch `feature/topgro`) |
| [Cablaggio Waveshare](docs/hardware-wiring.md) | Pinout e schema audio |
| [Deploy reale](docs/deployment-real.md) | Note storiche deploy (parzialmente datate) |

---

## Branch di sviluppo

| Branch | Scopo |
|--------|--------|
| `main` | Stato stabile ESP32 + Jetson |
| `feature/topgro` | Migrazione pipeline sul gaming PC (TOPGRO) |

---

## Dipendenze principali

| Componente | Libreria | Note |
|------------|----------|------|
| ASR | faster-whisper | `whisper-small`, italiano, CPU su Jetson 8GB |
| LLM | llama-cpp-python | Phi-3-mini Q4, GPU |
| TTS | piper-tts | `it_IT-paola-medium` |
| Wake word | ESP-SR WakeNet9 | `wn9_heykira_tts3` |
