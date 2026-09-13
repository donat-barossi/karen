# Jarvis – Assistente Vocale Domestico Offline

Assistente vocale **offline** in italiano (nome utente: **Jarvis**; codice e servizi: `karen`):

| Nodo | Hardware | Ruolo |
|------|----------|-------|
| Nodo audio | ESP32-S3 Waveshare | Wake word «Jarvis» · mic · speaker · UDP |
| Cervello AI | TOPGRO PC *(ex Jetson)* | ASR → LLM → TTS |
| Server casa | Mini PC | Home Assistant · automazioni |

---

## Flusso di una richiesta

```
[Utente: "Jarvis" + comando in italiano]
      │
      ▼
ESP32-S3 ── registra e invia UDP in streaming (16 kHz PCM)
      │
      ▼
Host AI (porta 7001) — profilo topgro o jetson
  ├─ Whisper small (trascrizione IT)
  ├─ Phi-3 Mini (intent JSON) o fast-path
  ├─ Skill engine (timer, sveglie, HA, meteo, musica…)
  └─ Piper TTS (voce Giorgio → resample 16 kHz)
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

Wake word: **«Jarvis»** (modello `wn9_jarvis_tts` in flash).

### 2. TOPGRO (PC gaming — host principale)

```bash
bash scripts/setup_topgro.sh
bash scripts/install_models.sh
cp host/config.yaml.example host/config.local.yaml   # token HA
bash host/scripts/install_systemd.sh topgro
sudo loginctl enable-linger $USER   # obbligatorio: Karen resta attiva senza SSH
```

Deploy aggiornamenti host:

```bash
bash scripts/deploy_topgro.sh   # test + copia + restart + verifica porta 7001
```

Test parser intent (regressioni):

```bash
python3 tests/test_intent_parsers.py
```

Verifica:

```bash
loginctl show-user $USER -p Linger    # deve essere Linger=yes
systemctl --user status karen-topgro
ss -ulnp | grep 7001
```

### 3. Jetson Orin Nano (fallback)

```bash
bash scripts/setup_jetson.sh
bash scripts/install_models.sh
bash host/scripts/install_systemd.sh jetson
sudo loginctl enable-linger $USER
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

Config: `host/config/base.yaml` + `host/config/{profile}.yaml` + override opzionale `host/config.local.yaml`

Modelli TTS predefiniti: **Giorgio** (`it_IT-giorgio-medium.onnx`). Assistente: nome **Jarvis** in `base.yaml`.

---

## Servizio systemd (importante)

Karen gira come **servizio utente** (`systemctl --user`). Senza **linger**, il servizio **si ferma quando chiudi l’ultima sessione SSH** — l’ESP rileva ancora «Jarvis» ma nessuno risponde sulla porta UDP 7001.

```bash
sudo loginctl enable-linger $USER
# oppure:
bash host/scripts/enable_boot.sh topgro
```

Vedi [setup-guide.md](docs/setup-guide.md) e [testing-and-debug.md](docs/testing-and-debug.md).

---

## Documentazione

| Documento | Contenuto |
|-----------|-----------|
| [Architettura](docs/architecture.md) | Protocollo UDP, stati ESP, pipeline |
| [Setup completo](docs/setup-guide.md) | Installazione passo-passo |
| [Test e debug](docs/testing-and-debug.md) | Debug per livello, linger, log ESP |
| [Migrazione TOPGRO](docs/topgro-migration.md) | Deploy su PC gaming (completata) |
| [Timer, sveglie, Outlook](docs/calendar-outlook.md) | Calendario, promemoria, query sveglie |
| [Musica](docs/music-setup.md) | Music Assistant + Navidrome |
| [Cablaggio Waveshare](docs/hardware-wiring.md) | Pinout e schema audio |
