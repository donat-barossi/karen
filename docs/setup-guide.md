# Guida di Setup Completa

## Prerequisiti

- **ESP32-S3** Waveshare AI Smart Speaker
- **Host AI:** TOPGRO PC (consigliato, IP es. `192.168.1.33`) o Jetson Orin Nano 8GB
- **Mini PC** con Home Assistant (opzionale, IP es. `192.168.1.67`)
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
- `it_IT-giorgio-medium.onnx` + `.json` (voce TTS maschile Jarvis)

### 1.2 Configurazione

Profilo in `host/config/topgro.yaml` (ASR CUDA). Override locale:

```bash
cp host/config.yaml.example host/config.local.yaml
nano host/config.local.yaml   # token HA, IP ESP32
```

Assistente e TTS in `host/config/base.yaml`:

```yaml
assistant:
  name: Jarvis
  greeting: "Ciao! Sono Jarvis, come posso aiutarti?"

tts:
  model_path: "it_IT-giorgio-medium.onnx"
  config_path: "it_IT-giorgio-medium.onnx.json"
```

### 1.3 Avvio e persistenza (obbligatorio)

Karen è un **servizio systemd utente**. Abilita il servizio **e** il linger:

```bash
bash host/scripts/install_systemd.sh topgro
sudo loginctl enable-linger $USER
```

Verifica:

```bash
loginctl show-user $USER -p Linger          # Linger=yes
systemctl --user is-enabled karen-topgro    # enabled
systemctl --user is-active karen-topgro     # active
ss -ulnp | grep 7001                        # python in ascolto
nvidia-smi
```

**Senza linger:** alla chiusura SSH Karen si ferma (`Stopped karen-topgro.service`). L’ESP continua a rilevare «Jarvis» ma non riceve risposta finché non ti riconnetti.

Alternativa one-shot:

```bash
bash host/scripts/enable_boot.sh topgro
```

### 1.4 Log

```bash
tail -f ~/karen/host/karen.log           # pipeline host
tail -f ~/karen/host/esp32.log           # log remoti ESP (solo se Karen attiva)
journalctl --user -u karen-topgro -f
```

---

## 2. Host AI – Jetson Orin Nano (fallback)

```bash
bash scripts/setup_jetson.sh
bash scripts/install_models.sh
bash host/scripts/install_systemd.sh jetson
sudo loginctl enable-linger $USER
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
#define WAKEWORD_MODEL_NAME "wn9_jarvis_tts"
```

```bash
~/.karen-pio-venv/bin/pio run -t upload --upload-port /dev/ttyACM0
```

- Wake word: **«Jarvis»**
- Fallback: tieni premuto **BOOT** ~0,5 s
- Verifica flash via log remoto: `build=…` e `thr=…` in `esp32.log`

---

## 4. Home Assistant

Token long-lived → `host/config.local.yaml` → `ha.token`

Package: `homeassistant/packages/karen.yaml`

---

## 5. Test

```bash
python3 scripts/test_pipeline.py --profile topgro --text "che ore sono"
python3 scripts/test_pipeline.py --profile topgro --text "quali sono le mie sveglie"
python3 scripts/test_pipeline.py --profile topgro --text "qual è la mia prossima sveglia"
```

End-to-end: **«Jarvis»** → comando in italiano.  
Vedi [testing-and-debug.md](testing-and-debug.md).

---

## Troubleshooting

| Problema | Causa probabile | Soluzione |
|----------|-----------------|-----------|
| Wake word OK, nessuna risposta | Host spento o linger=no | `systemctl --user status karen-topgro`; `sudo loginctl enable-linger $USER` |
| Host non risponde dopo reboot | Linger non abilitato | `bash host/scripts/enable_boot.sh topgro` |
| CUDA assente | Driver NVIDIA | `nvidia-smi`, reinstall driver |
| ASR OOM su TOPGRO | VRAM insufficiente | `compute_type: int8_float16` in topgro.yaml |
| ESP non raggiunge host | IP errato | `KAREN_HOST_IP` in `esp32/src/config.h` |
| Wake word intermittente | Sensibilità AFE | Vedi `WAKENET_THRESHOLD` in `config.h`; log `esp32.log` |
| Sveglie non elencate | Query mal routata | Aggiorna host; comandi «quali sveglie», «prossima sveglia» |
