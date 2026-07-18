# Migrazione pipeline su TOPGRO (gaming PC)

## Architettura adottata

La cartella **`jetson/` è stata rinominata in `host/`**: un solo codice Python con profili piattaforma, senza duplicare la pipeline.

```
host/
├── config/
│   ├── base.yaml      # transport, HA, modelli, logging
│   ├── jetson.yaml    # ASR CPU (Orin 8GB)
│   └── topgro.yaml    # ASR CUDA (GTX 1650)
├── karen/             # pipeline condivisa
├── scripts/
│   start_karen.sh     # LD paths aarch64 vs x86_64
│   install_systemd.sh # jetson | topgro
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
git checkout feature/topgro

bash scripts/setup_topgro.sh
bash scripts/install_models.sh
cp host/config.yaml.example host/config.yaml   # token HA

bash host/scripts/install_systemd.sh topgro
sudo loginctl enable-linger $USER
```

Test:

```bash
export KAREN_PROFILE=topgro
python3 scripts/test_pipeline.py --profile topgro --text "che ore sono"
systemctl --user status karen-topgro
ss -ulnp | grep 7001
```

---

## ESP32

In `esp32/src/config.h`:

```cpp
#define KAREN_HOST_IP  "192.168.1.33"
```

(`JETSON_IP` è un alias retrocompatibile nel firmware.)

---

## Jetson esistente (192.168.1.96)

Dopo `git pull`:

```bash
# Il path cambia: jetson/ → host/
bash host/scripts/install_systemd.sh jetson
systemctl --user disable karen-jetson.service  # se punta al vecchio path
```

Oppure symlink temporaneo: `ln -s host ~/karen/jetson`

---

## Tuning GTX 1650 (4 GB VRAM)

| Componente | TOPGRO | Note |
|------------|--------|------|
| ASR Whisper | GPU float16 | PyPI wheel CUDA x86 |
| LLM Phi-3 Q4 | GPU | `n_gpu_layers: -1` |
| TTS Piper | CPU | `use_cuda: false` per risparmiare VRAM |

Se OOM: ridurre `context_length` LLM o usare Whisper `int8_float16`.
