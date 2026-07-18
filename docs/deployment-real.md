# Karen – Guida di Deploy Reale (testata)

> **Nota (2026):** Parti di questo documento descrivono il primo prototipo (INMP441, PSRAM disabilitata, trigger BOOT).  
> Per lo **stato attuale** (Waveshare, wake word Hey Kira, streaming UDP, systemd) usa:
> - [setup-guide.md](setup-guide.md)
> - [testing-and-debug.md](testing-and-debug.md)
> - [hardware-wiring.md](hardware-wiring.md)

---

## Indice

1. [Il tuo hardware ESP32](#1-il-tuo-hardware-esp32)
2. [Flash del firmware ESP32-S3 – passo per passo](#2-flash-del-firmware-esp32-s3)
3. [Home Assistant in Docker sul Mini PC](#3-home-assistant-in-docker)
4. [Pipeline AI sul Jetson (recap)](#4-pipeline-ai-sul-jetson)
5. [Problema microfono – stato attuale](#5-problema-microfono)
6. [Carico sul Mini PC](#6-carico-sul-mini-pc)

---

## 1. Il tuo hardware ESP32

**Modulo:** ESP32-S3-WROOM-1-**N16R8**
- **16 MB Flash** (NOR SPI)
- **8 MB PSRAM** (OPI – Octal SPI)
- USB via chip **QinHeng CH9102** → `/dev/ttyACM0`

### Perché il firmware dice "2MB"?

Durante il primo deploy è emerso un crash (Guru Meditation) al boot causato dall'abilitazione della PSRAM OPI con parametri sbagliati. Per sbloccare rapidamente abbiamo:

1. Disabilitato tutta la PSRAM in `sdkconfig.defaults`
2. Impostato `flash_size = 2MB` in `platformio.ini` come valore conservativo

Il toolchain poi riportava "8MB Flash" perché rilevava la dimensione reale, ma la partition table era da 2MB. **Il modulo ha davvero 16MB di flash.**

### Cosa fare (quando si vuole usare la flash completa e la PSRAM)

```ini
# platformio.ini
board_build.flash_size = 16MB
board_build.flash_mode = qio
```

```text
# sdkconfig.defaults – riabilita PSRAM OPI (per N16R8)
CONFIG_SPIRAM=y
CONFIG_SPIRAM_MODE_OCT=y
CONFIG_SPIRAM_SPEED_80M=y
CONFIG_SPIRAM_BOOT_INIT=y
CONFIG_SPIRAM_IGNORE_NOTFOUND=y
```

> **Nota:** La PSRAM è necessaria per caricare i modelli wake word di ESP-SR direttamente sul modulo. Senza PSRAM il firmware gira comunque, ma il wake word è disabilitato e si usa il pulsante BOOT come trigger.

### Partition table 16MB consigliata

```csv
# Name,   Type, SubType, Offset,   Size,     Flags
nvs,      data, nvs,     0x9000,   0x6000,
phy_init, data, phy,     0xF000,   0x1000,
factory,  app,  factory, 0x10000,  0x200000,   # 2MB app
srmodel,  data, spiffs,  0x210000, 0x200000,   # 2MB wake word model
spiffs,   data, spiffs,  0x410000, 0x400000,   # 4MB dati utente
```

---

## 2. Flash del firmware ESP32-S3

### Prerequisiti sul laptop/PC di sviluppo

```bash
# 1. Python venv con PlatformIO
python3 -m venv ~/.karen-pio-venv
source ~/.karen-pio-venv/bin/activate
pip install platformio
# PlatformIO installa automaticamente toolchain ESP-IDF al primo build

# 2. Permessi USB (Linux)
sudo usermod -aG dialout $USER
# Poi rilogga o usa: newgrp dialout
```

### File da configurare prima del flash

#### `esp32/src/config.h`
```cpp
#define WIFI_SSID    "TuaRete"
#define WIFI_PASS    "TuaPassword"
#define JETSON_IP    "192.168.1.96"   // IP del Jetson
```

Gli altri parametri (GPIO, porte UDP) possono rimanere invariati se il cablaggio è uguale a quello in `hardware-wiring.md`.

#### `esp32/platformio.ini` – impostazioni attuali (firmware funzionante)
```ini
[env:esp32s3]
platform   = espressif32
board      = esp32-s3-devkitc-1
framework  = espidf

board_build.flash_size = 2MB      ; TODO: cambiare a 16MB + aggiornare partitions.csv
board_build.flash_mode = dio

custom_sdkconfig_options =
    CONFIG_ESP_CONSOLE_UART_DEFAULT=y

board_build.partitions = partitions.csv
```

> **Per il secondo nodo:** se vuoi abilitare la PSRAM e usare i 16MB completi, aggiorna `flash_size = 16MB`, `flash_mode = qio`, `partitions.csv` e `sdkconfig.defaults` come descritto nella sezione 1.

#### `esp32/sdkconfig.defaults` – impostazioni attuali (PSRAM disabilitata)
```
CONFIG_SPIRAM=n
CONFIG_ESP_CONSOLE_UART_DEFAULT=y
```

### Procedura di flash

```bash
# Collega ESP32 via USB → appare come /dev/ttyACM0
ls /dev/ttyACM*

# Entra nella directory esp32
cd /path/to/karen/esp32

# Attiva l'ambiente PlatformIO
source ~/.karen-pio-venv/bin/activate

# Compila
pio run --environment esp32s3

# Compila + flasha
pio run --environment esp32s3 --target upload

# Se /dev/ttyACM0 non viene rilevato automaticamente:
pio run --environment esp32s3 --target upload --upload-port /dev/ttyACM0
```

### Verifica che l'ESP32 sia online

Dopo il flash l'ESP32 si riavvia, si connette al Wi-Fi (~5 secondi) e riceve un IP dal router.

```bash
# Trova l'IP sul router (esempio con nmap)
nmap -sn 192.168.1.0/24 | grep -i esp

# Oppure pingalo se conosci già l'IP (dal log del router)
ping 192.168.1.XX
```

> **Nota sul serial log:** L'ESP32-S3 WROOM stampa i log sull'interfaccia USB-JTAG nativa (porta separata), **non** su `/dev/ttyACM0` (che è il CH9102). Per leggere i log serve un secondo adattatore USB sul pin TX0/RX0, oppure usare il monitor JTAG di PlatformIO su Linux con `openocd`.

### Bug noti e fix applicati al firmware

| Bug | Causa | Fix |
|-----|-------|-----|
| Guru Meditation al boot | PSRAM OPI abilitata senza corretta configurazione | Disabilitata PSRAM in `sdkconfig.defaults` |
| `esp_wn_iface.h` not found | `idf_component.yml` nella cartella sbagliata | Spostato in `esp32/src/` (non root del progetto) |
| ESP-SR v2 API incompatibile | Codice scritto per v1, componente scaricato v2 | Riscritti `wake_word.h` e `wake_word.cpp` per API v2 |
| Wake word non funziona | Partizione `srmodel` non presente (table 2MB) | Fallback su pulsante GPIO0 (BOOT) |
| Speaker muto | Stato `STATE_SPEAKING` mai impostato | Fix in `playback_task`: setta stato prima del loop |
| Audio distorto/velocizzato | Speaker init a 16000 Hz, Piper invia 22050 Hz | Aggiunto `SPK_SAMPLE_RATE 22050` in config.h |

### Trigger attuale: pulsante BOOT (GPIO0)

Poiché il wake word è disabilitato, per attivare Karen:
1. **Tieni premuto** il pulsante BOOT sull'ESP32 per circa 1 secondo
2. Rilascia → LED o comportamento cambierà (LISTENING)
3. Parla il comando
4. Dopo ~1.5s di silenzio, l'ESP32 smette di registrare e invia al Jetson

---

## 3. Home Assistant in Docker

### Sul Mini PC (o qualsiasi Linux con Docker)

#### Installa Docker
```bash
# Rimuovi versioni vecchie
sudo apt remove docker docker-engine docker.io containerd runc 2>/dev/null

# Aggiungi repo ufficiale Docker
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update && sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Permessi senza sudo
sudo usermod -aG docker $USER
newgrp docker
```

#### Copia i file di configurazione
```bash
# Dalla repo Karen:
cd /path/to/karen

# Crea la directory dei dati HA dove preferisci (esempio: /opt/homeassistant)
sudo mkdir -p /opt/homeassistant/config/packages
sudo chown -R $USER:$USER /opt/homeassistant
```

#### `docker-compose.yml`
```yaml
services:
  homeassistant:
    container_name: karen-homeassistant
    image: ghcr.io/home-assistant/home-assistant:stable
    volumes:
      - /opt/homeassistant/config:/config
      - /etc/localtime:/etc/localtime:ro
    network_mode: host          # necessario per discovery LAN (mDNS, SSDP)
    restart: unless-stopped
    privileged: false
```

> `network_mode: host` è **obbligatorio** per il discovery Bluetooth/mDNS dei dispositivi smart home.

#### `configuration.yaml` minima
```yaml
homeassistant:
  name: Casa
  latitude: 45.4654
  longitude: 9.1859
  unit_system: metric
  time_zone: Europe/Rome
  packages: !include_dir_named packages   # carica karen.yaml

http:
  trusted_proxies:
    - 127.0.0.1
    - 192.168.1.0/24
  ip_ban_enabled: false
```

#### Copia il package Karen
```bash
cp homeassistant/packages/karen.yaml /opt/homeassistant/config/packages/
```

#### Avvia
```bash
cd /path/to/karen/homeassistant/docker
docker compose up -d

# Verifica
docker logs karen-homeassistant -f --tail 20

# Test HTTP
curl -s -o /dev/null -w "%{http_code}" http://localhost:8123/api/
# → 401 = HA risponde (non autenticato, normale)
```

#### Primo accesso e token
1. Apri `http://IP-MINIPC:8123`
2. Completa onboarding (crea account admin)
3. **Profilo** (icona in basso a sinistra) → **Long-Lived Access Tokens** → **Create Token**
4. Dai nome `karen-jetson` e copia il token
5. Sul Jetson: `nano /home/donat/karen/jetson/config.yaml` → sostituisci il valore di `ha.token`

#### Comandi utili
```bash
docker compose restart          # riavvia
docker compose down             # ferma
docker compose pull && docker compose up -d  # aggiorna HA all'ultima versione
docker exec -it karen-homeassistant bash     # shell dentro il container
```

---

## 4. Pipeline AI sul Jetson (recap)

Il Jetson ha già tutto configurato. Per un nuovo Jetson:

```bash
# Sync codice
rsync -av /path/to/karen/jetson/ donat@192.168.1.96:/home/donat/karen/jetson/

# SSH sul Jetson
ssh donat@192.168.1.96
cd /home/donat/karen/jetson

# Crea venv
python3 -m venv venv
source venv/bin/activate

# Installa dipendenze base
pip install faster-whisper piper-tts aiohttp numpy scipy pyyaml python-dateutil huggingface_hub

# Installa llama-cpp-python con CUDA (Orin = SM 8.7, ~30 minuti)
CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=87" \
  pip install llama-cpp-python --no-cache-dir

# Scarica modelli
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('Systran/faster-whisper-small', local_dir='models/whisper-small-ct2')
"
wget -P models/ https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx
wget -P models/ https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx.json
wget -P models/ https://huggingface.co/bartowski/Phi-3-mini-4k-instruct-GGUF/resolve/main/Phi-3-mini-4k-instruct-Q4_K_M.gguf \
     -O models/phi3-mini-4k-q4_k_m.gguf
```

### `config.yaml` – valori da impostare
```yaml
transport:
  esp32_ip: "192.168.1.88"    # IP dell'ESP32 (vedi router)

ha:
  url: "http://192.168.1.XX:8123"   # IP del Mini PC
  token: "eyJ..."                    # token generato da HA

asr:
  device: "cpu"           # ctranslate2 PyPI non ha CUDA per aarch64
  compute_type: "int8"

llm:
  n_gpu_layers: 20         # 20 su Orin Nano (8GB) con Whisper già in memoria
  context_length: 1024
```

### Avvio come servizio systemd
```bash
sudo cp systemd/karen-jetson.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now karen-jetson
sudo systemctl status karen-jetson
```

### Verifica pipeline funzionante
```bash
source venv/bin/activate
python3 - << 'EOF'
import asyncio, yaml, sys
sys.path.insert(0, ".")
from karen.pipeline import KarenPipeline

async def test():
    cfg = yaml.safe_load(open("config.yaml"))
    p = KarenPipeline(cfg)
    await p.initialize()
    print("Pipeline pronta!")
    # Test con audio silenzioso → risposta "Non ho capito"
    audio = bytes(16000 * 2)  # 1s silenzio
    pcm = await p.process(audio)
    print(f"Risposta TTS: {len(pcm)} bytes = {len(pcm)/(22050*2):.1f}s")
    await p.shutdown()

asyncio.run(test())
EOF
```

---

## 5. Problema microfono – stato attuale

Il microfono INMP441 è fisicamente collegato correttamente (L/R = GND = canale sinistro), ma il Jetson riceve audio silenzioso. Il log mostra:
```
VAD filter removed 00:07.520 of audio  →  ASR → ''
```

**Ipotesi più probabile:** il segnale I2S viene letto ma con ampiezza molto bassa. Il codice in `i2s_audio.cpp` fa `raw32[i] >> 16` per estrarre i 16 bit superiori dei 24 bit utili dell'INMP441. Se il microfono è fisicamente distante o c'è un problema di connessione, il VAD di Whisper filtra tutto.

**Prossimi passi per debug:**
1. Verifica con un oscilloscopio o logic analyzer che GPIO2 abbia segnale I2S
2. Abbassa la soglia VAD in `asr.py`:
   ```python
   vad_parameters={"min_silence_duration_ms": 300, "threshold": 0.2}
   ```
3. Disabilita temporaneamente il VAD per vedere la trascrizione grezza:
   ```yaml
   # config.yaml
   asr:
     vad_filter: false
   ```
4. Controlla le connessioni fisiche SCK (GPIO41), WS (GPIO42), SD (GPIO2)

---

## 6. Carico sul Mini PC

Home Assistant in Docker è **molto leggero**:

| Risorsa | Idle | Con automazioni attive | Peak (avvio) |
|---------|------|----------------------|--------------|
| CPU | 1–3% | 3–8% | 15–25% (30s) |
| RAM | 250–400 MB | 350–500 MB | ~500 MB |
| Disco | ~600 MB installazione | cresce ~50 MB/mese (history) | – |
| Rete | trascurabile | trascurabile | – |

Un qualsiasi Mini PC moderno (anche N100, Celeron, Ryzen 3) gestisce HA senza nessun problema con abbondante margine. Il consumo cresce leggermente se abiliti molte integrazioni (telecamere, Energy dashboard con history lunga, ecc.).

### Limitare la storia per ridurre disco e CPU
```yaml
# configuration.yaml
recorder:
  purge_keep_days: 7        # default 10
  exclude:
    entity_globs:
      - sensor.sun*
      - weather.*
```
