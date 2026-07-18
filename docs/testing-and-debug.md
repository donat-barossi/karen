# Test e debug della pipeline Karen

Guida operativa per verificare ogni livello del sistema: ESP32 → UDP → Jetson (ASR → LLM → TTS) → UDP → speaker.

## Architettura attuale (riepilogo)

| Nodo | IP esempio | Ruolo |
|------|------------|-------|
| ESP32-S3 Waveshare | 192.168.1.89 | Wake word, mic, speaker, UDP |
| Jetson Orin Nano | 192.168.1.96 | Pipeline AI |
| Mini PC HA | 192.168.1.67 | Home Assistant (timer, luci, meteo) |

**Porte UDP:** ESP→Jetson **7001**, Jetson→ESP **7002**  
**Audio:** PCM 16-bit mono **16 kHz** (ESP e risposta TTS resample a 16 kHz)

---

## Checklist rapida end-to-end

Prima di un test vocale completo, verifica in ordine:

```bash
# 1. Jetson: servizio attivo e porta in ascolto
ssh donat@192.168.1.96 'systemctl --user is-active karen-jetson; ss -ulnp | grep 7001'

# 2. ESP32: ping e log serial
ping -c 2 192.168.1.89

# 3. Rete: firewall non blocca UDP 7001/7002
# (sul Jetson di solito non serve ufw se tutto in LAN)
```

Poi sul ESP32: **"Hey Kira"** → comando in italiano (es. *"Che ore sono?"*).

---

## Livello 1 – Solo pipeline Jetson (senza ESP32)

Utile per isolare ASR, LLM, TTS e skills.

### Prerequisiti

```bash
cd jetson
cp config.yaml.example config.yaml   # se non esiste già
# Modifica IP/token HA in config.yaml
bash scripts/start_karen.sh          # oppure: python3 main.py
```

Modelli in `jetson/models/` (non in git): Whisper, Phi-3, Piper.  
Vedi `scripts/install_models.sh`.

### Test da testo (bypass ASR)

Testa LLM + skills + TTS senza audio:

```bash
cd /path/to/karen
python3 scripts/test_pipeline.py --text "che ore sono"
python3 scripts/test_pipeline.py --text "che tempo fa oggi"
python3 scripts/test_pipeline.py --text "accendi le luci del salotto"
```

Output atteso: intent JSON, risposta italiana, file `/tmp/karen_response.wav`.

### Test pipeline completa con WAV

Registra un WAV **mono 16 kHz 16-bit** (o converti con ffmpeg):

```bash
ffmpeg -i mia_prova.m4a -ar 16000 -ac 1 -sample_fmt s16 test.wav
python3 scripts/test_pipeline.py --audio test.wav
```

Log attesi sul Jetson:

```
ASR → 'che ore sono'  (X.XX s)
Fast-path intent=time  (X.XX s)
Skill → '...'  (X.XX s)
TTS → N campioni @ 16000 Hz  (X.XX s)
Pipeline totale: X.XX s
```

### Test interattivo

```bash
python3 scripts/test_pipeline.py --interactive
```

---

## Livello 2 – Transport UDP Jetson

Con Karen in esecuzione, simula l'ESP32 inviando pacchetti KARN:

```bash
python3 - <<'PY'
import socket, struct, time
MAGIC = 0x4B41524E
def pkt(t, seq, payload=b""):
    return struct.pack(">IBBh", MAGIC, t, 0, seq) + payload

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
jetson = ("192.168.1.96", 7001)
pcm = b"\x00\x01" * 512
sock.sendto(pkt(0x01, 0, pcm), jetson)
time.sleep(0.05)
sock.sendto(pkt(0x02, 0), jetson)  # END_AUDIO
print("Inviato END_AUDIO")
PY
```

Log Jetson attesi:

```
Inizio upload stream da ('...', ...)
Upload stream chiuso (END): ...
ASR → ...
Risposta audio inviata a ('192.168.1.89', 7002): ...
```

Se non compare `Inizio upload stream`, il servizio non è in ascolto o c’è un firewall.

---

## Livello 3 – ESP32 (firmware)

### Build e flash

```bash
cd esp32
cp src/config.h.example src/config.h
# Imposta WIFI_SSID, WIFI_PASS, JETSON_IP

~/.karen-pio-venv/bin/pio run -t upload --upload-port /dev/ttyACM0
```

### Monitor serial

```bash
~/.karen-pio-venv/bin/pio device monitor --port /dev/ttyACM0 --baud 115200
```

### Sequenza log normale (happy path)

```
I karen_main: >>> Karen! Ascolto…
I udp_transport: RX risposta armato
I karen_main: Fine registrazione (silenzio=…, tot=…)
I karen_main: Riproduzione risposta (stream)…
I karen_main: Stream avviato (seq=0)
I karen_main: Stream finito: seq 0..N, riprodotti=N, validi=N
I karen_main: Risposta terminata
```

### Log utili per il debug

| Log ESP32 | Significato |
|-----------|-------------|
| `udp_transport: Task TX UDP avviato` | Upload verso Jetson con pacing 32 ms |
| `udp_transport: Coda TX piena` | Jetson lento o Wi-Fi congestionato |
| `Timeout attesa prima risposta Jetson` | Jetson non risponde / non in ascolto |
| `Skip seq=N (gap)` | Pacchetti UDP persi in downlink |
| `Recovery → IDLE` | Supervisor ha resettato uno stato bloccato |

---

## Livello 4 – Jetson in produzione

### Avvio e restart

```bash
# Servizio utente (consigliato)
systemctl --user start karen-jetson
systemctl --user restart karen-jetson
systemctl --user status karen-jetson

# Log
tail -f ~/karen/jetson/karen.log
```

Installazione servizio (prima volta):

```bash
bash jetson/scripts/install_systemd.sh
# Boot automatico senza login:
sudo loginctl enable-linger $USER
```

### Log pipeline per fase

| Messaggio | Fase |
|-----------|------|
| `Upload stream: X.X s ricevuti` | Ricezione streaming ESP→Jetson |
| `Upload stream chiuso (VAD Jetson)` | Fine utterance anticipata (700 ms silenzio) |
| `Upload stream chiuso (END)` | Fine da pacchetto END ESP |
| `ASR → '...'` | Trascrizione Whisper |
| `Fast-path intent=...` | Comando frequente senza LLM |
| `LLM → '...'` | Risposta modello |
| `Skill → '...'` | Esecuzione skill (HA, meteo, …) |
| `TTS → N campioni` | Sintesi Piper |
| `Risposta audio inviata` | Downlink UDP in tempo reale |

### Debug verbose

In `jetson/config.yaml`:

```yaml
logging:
  level: "DEBUG"
```

---

## Livello 5 – Test end-to-end completo

1. Avvia Jetson (`systemctl --user status karen-jetson` → `active`)
2. Monitor ESP32 + log Jetson in parallelo:

```bash
# Terminale 1
ssh donat@192.168.1.96 'tail -f ~/karen/jetson/karen.log'

# Terminale 2
~/.karen-pio-venv/bin/pio device monitor --port /dev/ttyACM0 --baud 115200
```

3. Di' **"Hey Kira"** → **"Che ore sono?"**
4. Verifica latenza totale (~10–25 s su Orin Nano: ASR CPU + LLM GPU + TTS)

---

## Troubleshooting

| Sintomo | Dove guardare | Azione |
|---------|---------------|--------|
| Jetson non riceve nulla | `ss -ulnp \| grep 7001` | `systemctl --user restart karen-jetson` |
| ASR vuoto / "Non ho capito" | Log `ASR → ''` | Verifica mic ESP; `vad_filter: false` in config |
| Risposta in inglese | Log LLM | Controlla `task: transcribe`, fast-path italiano |
| Audio ESP spezzato | Log `Skip seq=` | Jetson invia in tempo reale (32 ms/pkt); Wi-Fi |
| ESP boot loop | Serial `alloc coda TX fallita` | Firmware aggiornato (coda TX in PSRAM) |
| Nessun audio ESP | Manca `Stream avviato` | Verifica IP Jetson in `config.h`, porta 7002 |
| HA non agisce | Log skill | Token HA in `config.yaml` |
| OOM Jetson | dmesg / crash | Whisper su CPU, LLM GPU; riduci `n_gpu_layers` |

### Verifica connettività UDP

```bash
# Dal PC di sviluppo (sostituisci IP)
nc -u -vz 192.168.1.96 7001
```

---

## Strumenti utili

| Comando | Scopo |
|---------|--------|
| `scripts/test_pipeline.py` | Test Jetson senza ESP |
| `jetson/scripts/start_karen.sh` | Avvio con LD_LIBRARY_PATH CUDA |
| `jetson/scripts/install_systemd.sh` | Servizio systemd utente |
| `scripts/publish_karen_repo.sh` | Push su GitHub |

---

## Prossimo passo: TOPGRO (gaming PC)

La migrazione della pipeline dal Jetson al PC TOPGRO (GTX 1650) è in corso sul branch `feature/topgro`.  
Obiettivo: Whisper + LLM su GPU x86, stesso protocollo UDP verso ESP32.
