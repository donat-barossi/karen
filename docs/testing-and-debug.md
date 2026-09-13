# Test e debug della pipeline Jarvis

Guida operativa per verificare ogni livello: ESP32 → UDP → host AI (ASR → LLM → TTS) → UDP → speaker.

## Architettura attuale (riepilogo)

| Nodo | IP esempio | Ruolo |
|------|------------|-------|
| ESP32-S3 Waveshare | 192.168.1.89 | Wake word «Jarvis», mic, speaker, UDP |
| **TOPGRO** (host principale) | 192.168.1.33 | Pipeline AI (CUDA) |
| Jetson Orin Nano (fallback) | 192.168.1.96 | Pipeline AI (CPU ASR) |
| Mini PC HA | 192.168.1.67 | Home Assistant |

**Porte UDP:** ESP → host **7001**, host → ESP **7002**  
**Audio:** PCM 16-bit mono **16 kHz**

---

## Checklist rapida end-to-end

```bash
# 1. Host TOPGRO: linger, servizio, porta
ssh donat@192.168.1.33 '
  loginctl show-user donat -p Linger
  systemctl --user is-active karen-topgro
  ss -ulnp | grep 7001
'

# 2. ESP32 raggiungibile
ping -c 2 192.168.1.89

# 3. Log host in tempo reale
ssh donat@192.168.1.33 'tail -f ~/karen/host/karen.log'
```

Poi sull’ESP: **«Jarvis»** → comando (es. *«Che ore sono?»*).

---

## Problema frequente: wake word sì, risposta no

**Sintomo:** l’ESP accende il LED / entra in ascolto, ma Jarvis non parla. Spesso dopo ore/giorni senza usare SSH.

**Causa:** Karen (`karen-topgro.service`) **non è in esecuzione**. Il servizio è `systemctl --user` e con **`Linger=no`** si ferma quando chiudi l’ultima sessione SSH.

**Verifica:**

```bash
ssh donat@192.168.1.33 '
  loginctl show-user donat -p Linger
  journalctl --user -u karen-topgro --since today | tail -5
  ss -ulnp | grep 7001 || echo "PORTA 7001 CHIUSA"
'
```

Cerca nel journal:

```
Stopped karen-topgro.service    # logout SSH senza linger
Started karen-topgro.service    # nuovo login SSH
```

**Fix permanente:**

```bash
sudo loginctl enable-linger donat
systemctl --user restart karen-topgro
```

I log ESP (`esp32.log`) mostrano `wake detected` anche con host spento — vengono scritti **solo quando Karen è attiva** (riceve UDP `PKT_TYPE_LOG`).

---

## Livello 1 – Solo pipeline host (senza ESP32)

```bash
cd host
cp ../host/config.yaml.example config.local.yaml
export KAREN_PROFILE=topgro
bash scripts/start_karen.sh          # oppure: venv/bin/python main.py
```

Modelli in `host/models/`. Vedi `scripts/install_models.sh`.

### Test da testo

```bash
python3 scripts/test_pipeline.py --profile topgro --text "che ore sono"
python3 scripts/test_pipeline.py --profile topgro --text "quali sono le mie sveglie"
python3 scripts/test_pipeline.py --profile topgro --text "qual è la mia prossima sveglia"
```

### Test con WAV

```bash
ffmpeg -i prova.m4a -ar 16000 -ac 1 -sample_fmt s16 test.wav
python3 scripts/test_pipeline.py --profile topgro --audio test.wav
```

Log attesi:

```
ASR → 'che ore sono'  (X.XX s)
Fast-path intent=time  (X.XX s)
Skill → '...'  (X.XX s)
TTS → N campioni @ 16000 Hz  (X.XX s)
```

---

## Livello 2 – Transport UDP

Con Karen in esecuzione, simula l’ESP32:

```bash
python3 - <<'PY'
import socket, struct, time
MAGIC = 0x4B41524E
def pkt(t, seq, payload=b""):
    return struct.pack(">IBBh", MAGIC, t, 0, seq) + payload

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
host = ("192.168.1.33", 7001)
pcm = b"\x00\x01" * 512
sock.sendto(pkt(0x01, 0, pcm), host)
time.sleep(0.05)
sock.sendto(pkt(0x02, 0), host)
print("Inviato END_AUDIO")
PY
```

Log attesi:

```
Inizio upload stream da ('...', ...)
Upload stream chiuso ...
ASR → ...
Risposta audio inviata a ('192.168.1.89', 7002): ...
```

---

## Livello 3 – ESP32 (firmware)

### Build e flash

```bash
cd esp32
cp src/config.h.example src/config.h
# WIFI_SSID, WIFI_PASS, KAREN_HOST_IP

~/.karen-pio-venv/bin/pio run -t upload --upload-port /dev/ttyACM0
```

### Monitor serial

```bash
~/.karen-pio-venv/bin/pio device monitor --port /dev/ttyACM0 --baud 115200
```

### Sequenza log normale

```
I karen_main: >>> Jarvis! Ascolto…
I karen_main: Fine registrazione ...
I karen_main: Riproduzione risposta (stream)…
I karen_main: Risposta terminata
```

### Log remoti (persistiti su host)

File: `~/karen/host/esp32.log`

| Messaggio | Significato |
|-----------|-------------|
| `ready ww=wn9_jarvis_tts build=…` | Firmware e soglia wake |
| `wake detected` | WakeNet ha triggerato |
| `wake rejected cooldown/ambient` | Wake scartato (gate/cooldown) |
| `wake afe reinit` | Recovery motore wake post-TTS |
| `HB … mic_rms=N` | Heartbeat; RMS microfono in IDLE |
| `state 0->1->2->3->0` | IDLE → ascolto → attesa → TTS → IDLE |

---

## Livello 4 – Host in produzione (TOPGRO)

```bash
systemctl --user status karen-topgro
systemctl --user restart karen-topgro
tail -f ~/karen/host/karen.log
tail -f ~/karen/host/esp32.log
journalctl --user -u karen-topgro -f
```

Installazione (prima volta):

```bash
bash host/scripts/install_systemd.sh topgro
sudo loginctl enable-linger $USER
```

### Log pipeline

| Messaggio | Fase |
|-----------|------|
| `Server UDP in ascolto su 0.0.0.0:7001` | Host pronto |
| `Upload stream: X.X s ricevuti` | Audio ESP → host |
| `Rule fast-path intent=alarm` | Sveglie/timer senza LLM |
| `ASR → '...'` | Trascrizione Whisper o Parakeet locale |

### Test Parakeet ASR (solo locale su Jetson)

Nessun dato inviato al cloud NVIDIA: il modello gira in Docker sul Jetson.

```bash
# Sul Jetson (192.168.1.96)
export NGC_API_KEY=...   # solo per pull immagine da nvcr.io
bash scripts/setup_riva_parakeet_jetson.sh

pip install nvidia-riva-client requests
ffmpeg -y -f alsa -i ... -t 5 -ar 16000 -ac 1 /tmp/prova.wav
python scripts/test_asr_backends.py --audio /tmp/prova.wav
```

Per usare Parakeet in Karen sul Jetson, in `config.local.yaml`:

```yaml
asr:
  backend: riva
  riva:
    mode: local_http
    http_url: http://127.0.0.1:9000/v1/audio/transcriptions
    fallback_whisper: true
```

TOPGRO può chiamare Parakeet sul Jetson via LAN (`http://192.168.1.96:9000/...`) senza cloud.
Torna a Whisper: `asr.backend: whisper`.
| `Fast-path intent=...` | Comando frequente senza LLM |
| `LLM → '...'` | Risposta modello |
| `Skill → '...'` | Skill (HA, meteo, sveglie…) |
| `TTS → N campioni` | Piper Giorgio |
| `Risposta audio inviata` | Downlink UDP |

Debug verbose in `host/config/base.yaml`:

```yaml
logging:
  level: "DEBUG"
```

---

## Livello 5 – Test end-to-end

1. Verifica host: `systemctl --user is-active karen-topgro` → `active`
2. Log paralleli:

```bash
ssh donat@192.168.1.33 'tail -f ~/karen/host/karen.log ~/karen/host/esp32.log'
```

3. Di' **«Jarvis»** → **«Che ore sono?»**
4. Latenza TOPGRO tipica: ~2–8 s (ASR+LLM su GPU)

---

## Troubleshooting

| Sintomo | Dove guardare | Azione |
|---------|---------------|--------|
| Wake sì, risposta no | `ss -ulnp \| grep 7001`, linger | `enable-linger`, restart servizio |
| Host non riceve UDP | Porta 7001 chiusa | `systemctl --user restart karen-topgro` |
| ASR vuoto | Log `ASR → ''` | Mic ESP; `vad_filter: false` |
| LLM inventa intent | Log `Intent LLM non valido` | Aggiorna host; fast-path sveglie |
| Audio ESP spezzato | Log `Skip seq=` | Wi-Fi; host lento |
| Wake intermittente | `esp32.log` senza `wake detected` | Reflash ESP; soglia in `config.h` |
| HA non agisce | Log skill | Token in `config.local.yaml` |

### Connettività UDP

```bash
nc -u -vz 192.168.1.33 7001
```

---

## Strumenti utili

| Comando | Scopo |
|---------|--------|
| `scripts/test_pipeline.py` | Test host senza ESP |
| `host/scripts/start_karen.sh` | Avvio manuale con CUDA paths |
| `host/scripts/install_systemd.sh topgro` | Servizio systemd utente |
| `host/scripts/enable_boot.sh topgro` | Abilita linger al boot |
| `~/.karen-pio-venv/bin/pio run -t upload` | Flash firmware ESP |
