# Karen – Assistente Vocale Domestico Offline

Assistente vocale **offline** in italiano:

| Nodo | Hardware | Ruolo |
|------|----------|-------|
| Nodo audio | ESP32-S3 Waveshare | Wake word · mic · speaker · UDP |
| Cervello AI | TOPGRO PC *(ex Jetson)* | ASR → LLM → TTS |
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
Host AI (porta 7001) — profilo jetson o topgro
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
├── host/           Pipeline AI Python (ASR · LLM · TTS · skills)
│   ├── config/     Profili base.yaml + jetson.yaml + topgro.yaml
│   └── karen/      Codice condiviso
├── homeassistant/  Package HA e docker-compose
├── scripts/        Setup, test e utilità
└── docs/           Architettura, cablaggio, setup, test/debug
```

---

## Quick start

### 1. ESP32-S3

```bash
cd esp32
cp src/config.h.example src/config.h   # Wi-Fi + KAREN_HOST_IP
~/.karen-pio-venv/bin/pio run -t upload --upload-port /dev/ttyACM0
```

### 2. TOPGRO (PC gaming)

```bash
bash scripts/setup_topgro.sh
bash scripts/install_models.sh
cp host/config.yaml.example host/config.yaml   # token HA
bash host/scripts/install_systemd.sh topgro
```

### 3. Jetson Orin Nano (fallback)

```bash
bash scripts/setup_jetson.sh
bash scripts/install_models.sh
bash host/scripts/install_systemd.sh jetson
```

### 4. Test senza ESP32

```bash
python3 scripts/test_pipeline.py --profile topgro --text "che ore sono"
```

---

## Profili piattaforma

| Profilo | `KAREN_PROFILE` | ASR | LLM |
|---------|-----------------|-----|-----|
| TOPGRO | `topgro` | CUDA float16 | GPU |
| Jetson | `jetson` | CPU float32 | GPU |

Config: `host/config/base.yaml` + `host/config/{profile}.yaml` + override opzionale `host/config.yaml`

---

## Documentazione

| Documento | Contenuto |
|-----------|-----------|
| [Architettura](docs/architecture.md) | Protocollo UDP, stati ESP, pipeline |
| [Setup completo](docs/setup-guide.md) | Installazione passo-passo |
| [Test e debug](docs/testing-and-debug.md) | Debug completo per livello |
| [Migrazione TOPGRO](docs/topgro-migration.md) | Piano e stato migrazione |
| [Timer, sveglie, Outlook](docs/calendar-outlook.md) | Calendario e promemoria |
| [Cablaggio Waveshare](docs/hardware-wiring.md) | Pinout e schema audio |

---

## Branch di sviluppo

| Branch | Scopo |
|--------|--------|
| `main` | Stato stabile |
| `feature/topgro` | Pipeline su PC gaming TOPGRO |
