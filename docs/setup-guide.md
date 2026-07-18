# Guida di Setup Completa

## Prerequisiti

- ESP32-S3 DevKit con INMP441 e MAX98357A cablati (vedi [hardware-wiring.md](hardware-wiring.md))
- Jetson Orin Nano con JetPack 6.x installato
- Mini PC con Home Assistant OS o Container
- Rete Wi-Fi locale (2.4/5 GHz)

---

## 1. Jetson Orin Nano

### 1.1 Setup dipendenze di sistema

```bash
bash scripts/setup_jetson.sh
```

Questo script installa:
- CUDA toolkit (già incluso in JetPack)
- Python 3.10+, pip, venv
- llama-cpp-python con backend CUDA
- faster-whisper
- piper-tts

### 1.2 Scaricare i modelli

```bash
bash scripts/install_models.sh
```

Scarica in `jetson/models/`:
- `whisper-small-ct2/` — faster-whisper small (CTranslate2)
- `phi3-mini-4k-q4_k_m.gguf` — LLM (~2.4 GB)
- `it_IT-paola-medium.onnx` + `.json` — voce Piper

### 1.3 Configurare Karen

```bash
cd jetson
cp config.yaml.example config.yaml
nano config.yaml
```

Parametri minimi da impostare:

```yaml
ha:
  url: "http://192.168.1.XX:8123"    # IP del tuo Mini PC
  token: "YOUR_HA_LONG_LIVED_TOKEN"

transport:
  jetson_listen_port: 7001           # porta UDP in ascolto
  esp32_ip: "192.168.1.YY"          # IP statico dell'ESP32
  esp32_port: 7002                   # porta UDP per risposta
```

### 1.4 Avviare Karen

```bash
cd jetson
python main.py
# oppure come servizio systemd:
sudo cp systemd/karen-jetson.service /etc/systemd/system/
sudo systemctl enable --now karen-jetson
```

---

## 2. ESP32-S3

### 2.1 Installare PlatformIO

```bash
pip install platformio
```

### 2.2 Configurare il firmware

```bash
cd esp32
cp src/config.h.example src/config.h
nano src/config.h
```

Valori da impostare:

```cpp
#define WIFI_SSID    "NomeReteCasa"
#define WIFI_PASS    "PasswordWiFi"
#define JETSON_IP    "192.168.1.XX"   // IP del Jetson
```

### 2.3 Compilare e flashare

```bash
pio run --target upload --upload-port /dev/ttyUSB0
pio device monitor --baud 115200
```

### 2.4 Wake word personalizzato "Ehi Karen"

Il firmware usa di default il modello **WakeNet9 "hilexin"** (placeholder).  
Per ottenere il wake word personalizzato "Ehi Karen":

1. Vai su [https://github.com/espressif/esp-sr](https://github.com/espressif/esp-sr)
2. Segui il processo di training custom wake word (richiede account Espressif)
3. Scarica il modello `.bin` generato
4. Sostituiscilo in `esp32/components/esp-sr/models/`

> **Alternativa:** usa il wake word "Hey Karen" (inglese) con WakeNet9,
> più semplice da riconoscere per il motore ESP-SR.

---

## 3. Home Assistant (Mini PC)

### 3.1 Abilitare i package

Nel file `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

### 3.2 Copiare il package Karen

```bash
cp homeassistant/packages/karen.yaml /config/packages/karen.yaml
```

Poi **Strumenti sviluppatore → Verifica configurazione → Riavvia**.

### 3.3 Generare il token API

1. Profilo HA → "Token di lunga durata"
2. Crea nuovo token, copialo in `jetson/config.yaml`

---

## 4. Test del sistema

```bash
# Testa solo la pipeline Jetson (senza ESP32)
cd scripts
python test_pipeline.py --text "che ore sono"
python test_pipeline.py --text "set a timer for 3 minutes"
python test_pipeline.py --text "recipe with peppers and shrimp"
```

---

## 5. Troubleshooting

| Sintomo | Causa probabile | Soluzione |
|---------|----------------|-----------|
| ESP32 non si connette al Wi-Fi | SSID/password errati | Ricontrolla `config.h` |
| Nessuna risposta dopo wake word | Jetson non raggiungibile | Verifica IP e firewall |
| ASR molto lento | Whisper usa CPU invece di CUDA | `pip install faster-whisper[cuda]` |
| LLM risponde male | Prompt non ottimale | Edita `SYSTEM_PROMPT` in `llm.py` |
| TTS voce non trovata | Modello non scaricato | Riesegui `install_models.sh` |
| HA non esegue azioni | Token scaduto o errato | Rigenera token in HA |
