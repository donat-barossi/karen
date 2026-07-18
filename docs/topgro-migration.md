# Migrazione pipeline su TOPGRO (gaming PC)

Obiettivo: spostare il **cervello AI** da Jetson Orin Nano al PC gaming **TOPGRO** (GTX 1650), mantenendo ESP32-S3 e Home Assistant invariati.

## Stato attuale vs target

| Componente | Jetson (attuale) | TOPGRO (target) |
|------------|------------------|-----------------|
| ASR Whisper | CPU float32 (OOM se GPU con LLM) | CUDA, modello più grande possibile |
| LLM Phi-3 | GPU llama-cpp | GPU CUDA, stesso GGUF o upgrade |
| TTS Piper | CPU | CPU o GPU se utile |
| UDP 7001/7002 | `192.168.1.96` | IP statico TOPGRO |
| ESP `JETSON_IP` | `config.h` | Rinominare / aggiornare IP TOPGRO |

## Piano di lavoro (branch `feature/topgro`)

1. **Ambiente x86_64**
   - Python venv, `setup_topgro.sh` (da creare da `setup_jetson.sh`)
   - CUDA + cuDNN compatibili con GTX 1650
   - `llama-cpp-python` build CUDA, `faster-whisper` GPU

2. **Config**
   - `topgro/config.yaml` o riuso `jetson/` con profilo device
   - ASR: `device: cuda`, `compute_type: float16`
   - LLM: `n_gpu_layers: -1`

3. **Servizio**
   - systemd user `karen-topgro.service` (stesso pattern Jetson)
   - Log in `~/karen/topgro/karen.log`

4. **ESP32**
   - Solo cambio IP in `esp32/src/config.h`:
     ```cpp
     #define JETSON_IP    "192.168.1.XXX"  // IP TOPGRO
     ```
   - Protocollo UDP KARN invariato

5. **Test**
   - Livelli 1–5 in [testing-and-debug.md](testing-and-debug.md) ripetuti con host TOPGRO
   - Confronto latenza Jetson vs TOPGRO

## File da aggiungere in questo branch

```
topgro/                    # Copia/adattamento jetson/karen/
scripts/setup_topgro.sh
jetson/systemd/karen-topgro.service   # o topgro/systemd/
docs/topgro-migration.md   # questo file
```

## Note hardware TOPGRO

- GTX 1650: 4 GB VRAM — sufficiente per Phi-3 Q4 + Whisper small in GPU con tuning batch
- Jetson resta fallback finché TOPGRO non è stabile in produzione
