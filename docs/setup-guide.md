# Guida di Setup Completa

## Prerequisiti

- **ESP32-S3** Waveshare AI Smart Speaker (ES8311 + ES7210 integrati)
- **Jetson Orin Nano** 8GB con JetPack 6.x
- **Mini PC** con Home Assistant (opzionale, per timer/luci)
- Rete Wi-Fi 2.4 GHz (ESP32)

---

## 1. Jetson Orin Nano

### 1.1 Dipendenze

```bash
bash scripts/setup_jetson.sh
bash scripts/install_models.sh
```

Modelli in `jetson/models/` (non versionati):

- `whisper-small-ct2/`
- `phi3-mini-4k-q4_k_m.gguf`
- `it_IT-paola-medium.onnx` + `.json`

### 1.2 Configurazione

```bash
cd jetson
cp config.yaml.example config.yaml
nano config.yaml
```

Parametri essenziali:

```yaml
transport:
  esp32_ip: "192.168.1.89"
  esp32_port: 7002

ha:
  url: "http://192.168.1.100:8123"
  token: "YOUR_HA_LONG_LIVED_TOKEN"

asr:
  device: "cpu"           # Whisper su CPU (evita OOM con LLM su GPU)
  task: "transcribe"
  language: "it"
  vad_filter: false

llm:
  n_gpu_layers: -1        # Phi-3 su GPU
```

### 1.3 Avvio

```bash
# Manuale
bash jetson/scripts/start_karen.sh

# Servizio systemd (consigliato)
bash jetson/scripts/install_systemd.sh
sudo loginctl enable-linger $USER   # avvio al boot
```

Verifica:

```bash
systemctl --user status karen-jetson
ss -ulnp | grep 7001
```

---

## 2. ESP32-S3

### 2.1 PlatformIO

```bash
python3 -m venv ~/.karen-pio-venv
~/.karen-pio-venv/bin/pip install platformio
```

### 2.2 Configurazione firmware

```bash
cd esp32
cp src/config.h.example src/config.h
```

```cpp
#define WIFI_SSID    "TuaRete"
#define WIFI_PASS    "TuaPassword"
#define JETSON_IP    "192.168.1.96"
```

### 2.3 Flash e monitor

```bash
~/.karen-pio-venv/bin/pio run -t upload --upload-port /dev/ttyACM0
~/.karen-pio-venv/bin/pio device monitor --port /dev/ttyACM0 --baud 115200
```

Log atteso: `Karen pronta (supervisor attivo).`

Wake word: **"Hey Kira"** (modello `wn9_heykira_tts3` in flash @ 0x210000).

---

## 3. Home Assistant

```bash
cp homeassistant/packages/karen.yaml /path/to/ha/config/packages/
```

Genera token in HA → Profilo → Long-Lived Access Tokens → incolla in `jetson/config.yaml`.

Docker: vedi `homeassistant/docker/docker-compose.yml`.

---

## 4. Test

### Pipeline Jetson (senza ESP)

```bash
python3 scripts/test_pipeline.py --text "che ore sono"
python3 scripts/test_pipeline.py --interactive
```

### End-to-end

1. Jetson attivo (`karen-jetson` active)
2. Monitor ESP32 + `tail -f ~/karen/jetson/karen.log`
3. "Hey Kira" → "Che ore sono?"

Guida debug completa: **[testing-and-debug.md](testing-and-debug.md)**

---

## 5. Troubleshooting rapido

| Problema | Soluzione |
|----------|-----------|
| Jetson non risponde | `systemctl --user restart karen-jetson` |
| ESP boot loop | Firmware aggiornato (coda TX PSRAM) |
| Audio spezzato | Verifica Wi-Fi; log `Skip seq=` |
| ASR vuoto | `vad_filter: false`; controlla mic |
| Risposta EN | `task: transcribe`, fast-path italiano |

---

## Cablaggio

Scheda Waveshare all-in-one: nessun cablaggio esterno mic/speaker.  
Dettagli: [hardware-wiring.md](hardware-wiring.md)
