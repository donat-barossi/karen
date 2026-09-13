# Migrazione pipeline su TOPGRO (completata)

La pipeline gira sul **PC gaming TOPGRO** (`192.168.1.33`). Il Jetson (`192.168.1.96`) resta disponibile come fallback.

## Architettura adottata

La cartella **`jetson/` è stata rinominata in `host/`**: un solo codice Python con profili piattaforma.

```
host/
├── config/
│   ├── base.yaml      # transport, HA, modelli, assistant Jarvis, TTS Giorgio
│   ├── jetson.yaml    # ASR CPU (Orin 8GB)
│   └── topgro.yaml    # ASR CUDA (GTX 1650)
├── karen/             # pipeline condivisa
├── data/
│   └── schedules.json # timer e sveglie
├── scripts/
│   start_karen.sh     # LD paths aarch64 vs x86_64
│   install_systemd.sh # jetson | topgro
│   enable_boot.sh     # linger (avvio senza login)
└── systemd/
    ├── karen-jetson.service
    └── karen-topgro.service
```

Variabile d'ambiente: **`KAREN_PROFILE=topgro`** o **`jetson`**.

---

## Deploy TOPGRO (192.168.1.33)

```bash
git clone git@github.com:donat-barossi/karen.git ~/karen
cd ~/karen

bash scripts/setup_topgro.sh
bash scripts/install_models.sh
cp host/config.yaml.example host/config.local.yaml   # token HA

bash host/scripts/install_systemd.sh topgro
sudo loginctl enable-linger $USER    # obbligatorio
```

Test:

```bash
export KAREN_PROFILE=topgro
python3 scripts/test_pipeline.py --profile topgro --text "che ore sono"
systemctl --user status karen-topgro
ss -ulnp | grep 7001
loginctl show-user $USER -p Linger
```

---

## ESP32

In `esp32/src/config.h`:

```cpp
#define KAREN_HOST_IP       "192.168.1.33"
#define WAKEWORD_MODEL_NAME "wn9_jarvis_tts"
```

(`JETSON_IP` è un alias retrocompatibile nel firmware.)

Wake word: **«Jarvis»**. Log remoto build tag in `host/esp32.log`.

---

## Jetson esistente (192.168.1.96)

Dopo `git pull`:

```bash
bash host/scripts/install_systemd.sh jetson
sudo loginctl enable-linger $USER
systemctl --user disable karen-topgro.service   # se non usi TOPGRO
```

Path log: `~/karen/host/karen.log` (non più `~/karen/jetson/`).

---

## Tuning GTX 1650 (4 GB VRAM)

| Componente | TOPGRO | Note |
|------------|--------|------|
| ASR Whisper | GPU float16 | PyPI wheel CUDA x86 |
| LLM Phi-3 Q4 | GPU | `n_gpu_layers: -1` |
| TTS Piper Giorgio | CPU | `use_cuda: false` |

Se OOM: ridurre `context_length` LLM o usare Whisper `int8_float16`.

---

## Checklist produzione

- [ ] `Linger=yes` per l'utente del servizio
- [ ] `systemctl --user is-enabled karen-topgro`
- [ ] Porta UDP 7001 in ascolto dopo reboot (test senza SSH)
- [ ] `KAREN_HOST_IP` nell'ESP punta al TOPGRO
- [ ] Token HA in `config.local.yaml`
- [ ] Modelli in `host/models/` (Whisper, Phi-3, Giorgio)
