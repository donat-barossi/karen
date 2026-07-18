# Karen – Assistente Vocale Domestico Offline

Assistente vocale **completamente offline** basato su:

| Nodo | Hardware | Ruolo |
|------|----------|-------|
| Nodo audio | ESP32-S3 | Wake word · cattura audio · riproduzione risposta |
| Cervello AI | Jetson Orin Nano | ASR → LLM → TTS |
| Server casa | Mini PC | Home Assistant · timer · automazioni |

---

## Flusso di una richiesta

```
[Utente parla]
      │
      ▼
ESP32-S3 ── wake word "Ehi Karen" ──► registra audio (INMP441)
      │
      │  UDP (PCM 16kHz)
      ▼
Jetson Orin Nano
  ├─ Whisper small  (translate IT→EN)
  ├─ Phi-3 Mini / Mistral 7B  (intent + risposta in JSON)
  ├─ Skill engine  (timer, HA, meteo, orologio, ricette…)
  └─ Piper TTS  (testo IT → audio)
      │
      │  UDP (PCM 22kHz)
      ▼
ESP32-S3 ── riproduce via MAX98357A + speaker
      │
      ▼ (se azione domotica)
Mini PC – Home Assistant REST API
```

---

## Struttura repository

```
karen/
├── esp32/          Firmware ESP32-S3 (PlatformIO + ESP-IDF)
├── jetson/         Pipeline AI Python (ASR · LLM · TTS · skills)
├── homeassistant/  Package HA (automazioni, script, timer)
├── scripts/        Setup e utilità
└── docs/           Cablaggio, architettura, guida setup
```

---

## Quick start

### 1. ESP32-S3

```bash
cd esp32
# Copia e modifica config.h con IP Jetson e credenziali WiFi
cp src/config.h.example src/config.h
pio run --target upload
```

### 2. Jetson Orin Nano

```bash
cd jetson
bash ../scripts/setup_jetson.sh       # installa dipendenze CUDA
bash ../scripts/install_models.sh     # scarica Whisper + LLM + Piper
pip install -r requirements.txt
cp config.yaml.example config.yaml    # edita IP e token HA
python main.py
```

### 3. Mini PC – Home Assistant

Copia `homeassistant/packages/karen.yaml` nella cartella `packages/` di HA  
e riavvia Home Assistant.

---

## Dipendenze principali

| Componente | Libreria | Note |
|------------|----------|------|
| ASR | faster-whisper | modello `small`, mode `translate` |
| LLM | llama-cpp-python (CUDA) | Phi-3-mini-4k Q4_K_M (≈2.2 GB) |
| TTS | piper-tts | voce `it_IT-paola-medium` |
| Wake word | ESP-SR WakeNet9 | custom "Ehi Karen" via Espressif portal |

---

## Documentazione

- [Architettura dettagliata](docs/architecture.md)
- [Cablaggio hardware](docs/hardware-wiring.md)
- [Guida di setup completa](docs/setup-guide.md)
