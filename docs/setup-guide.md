# Guida di Setup Completa

## Prerequisiti

- **ESP32-S3** Waveshare AI Smart Speaker
- **Host AI:** TOPGRO PC (consigliato) o Jetson Orin Nano 8GB
- **Mini PC** con Home Assistant (opzionale)
- Rete Wi-Fi 2.4 GHz (ESP32)

---

## 1. Host AI – TOPGRO (PC gaming)

### 1.1 Dipendenze

```bash
bash scripts/setup_topgro.sh
bash scripts/install_models.sh
```

Modelli in `host/models/`:

- `whisper-small-ct2/`
- `phi3-mini-4k-q4_k_m.gguf`
- `it_IT-paola-medium.onnx` + `.json`

### 1.2 Configurazione

Profilo in `host/config/topgro.yaml` (ASR CUDA). Override locale:

```bash
cp host/config.yaml.example host/config.yaml
nano host/config.yaml   # token HA, IP ESP32
```

### 1.3 Avvio

```bash
export KAREN_PROFILE=topgro
bash host/scripts/install_systemd.sh topgro
sudo loginctl enable-linger $USER
```

Verifica:

```bash
systemctl --user status karen-topgro
ss -ulnp | grep 7001
nvidia-smi
```

---

## 2. Host AI – Jetson Orin Nano (fallback)

```bash
bash scripts/setup_jetson.sh
bash scripts/install_models.sh
bash host/scripts/install_systemd.sh jetson
```

Profilo `host/config/jetson.yaml`: Whisper su CPU, LLM su GPU.

---

## 3. ESP32-S3

```bash
cd esp32
cp src/config.h.example src/config.h
```

```cpp
#define KAREN_HOST_IP  "192.168.1.33"   // IP TOPGRO
```

```bash
~/.karen-pio-venv/bin/pio run -t upload --upload-port /dev/ttyACM0
```

Wake word: **"Hey Kira"**

---

## 4. Home Assistant

Token long-lived → `host/config.yaml` → `ha.token`

---

## 5. Test

```bash
python3 scripts/test_pipeline.py --profile topgro --text "che ore sono"
```

End-to-end: "Hey Kira" → comando in italiano.  
Vedi [testing-and-debug.md](testing-and-debug.md).

---

## Troubleshooting

| Problema | Soluzione |
|----------|-----------|
| Host non risponde | `systemctl --user restart karen-topgro` |
| CUDA assente | `nvidia-smi`, reinstall driver |
| ASR OOM su TOPGRO | `compute_type: int8_float16` in topgro.yaml |
| ESP non raggiunge host | Verifica `KAREN_HOST_IP` in config.h |
