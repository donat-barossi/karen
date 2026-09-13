#!/usr/bin/env bash
# nano-parakeet (PyTorch GPU) su Jetson Orin — solo STT locale.
#
# Prerequisiti: JetPack 6.x, Python 3.10 venv in ~/karen/jetson/venv
#
# Uso:
#   bash scripts/setup_nano_parakeet_jetson.sh
#   systemctl --user enable --now karen-parakeet-asr
#   curl -s http://127.0.0.1:9000/v1/health/ready
#
# Ferma altri servizi Karen sul Jetson prima (Whisper, pipeline completa):
#   systemctl --user stop karen-whisper-asr karen-jetson

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
JETSON_DIR="${KAREN_JETSON_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
VENV="${JETSON_DIR}/venv"
PYTHON="${VENV}/bin/python"
PIP="${VENV}/bin/pip"
SERVICE_SRC="${JETSON_DIR}/systemd/karen-parakeet-asr.service"

export LD_LIBRARY_PATH="${HOME}/.local/lib:/usr/lib/aarch64-linux-gnu/openblas-pthread:/usr/local/cuda/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# JetPack 6.1 — wheel PyTorch NVIDIA aarch64 (cp310)
TORCH_WHEEL="${TORCH_WHEEL:-https://developer.download.nvidia.com/compute/redist/jp/v61/pytorch/torch-2.5.0a0+872d972e41.nv24.08.17622132-cp310-cp310-linux_aarch64.whl}"

if [ ! -x "$PYTHON" ]; then
  echo "venv non trovato: $VENV — esegui prima scripts/setup_jetson.sh" >&2
  exit 1
fi

echo "=== nano-parakeet su Jetson (PyTorch CUDA) ==="
echo "venv: $VENV"

"$PIP" install -q --upgrade pip

if ! "$PYTHON" -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
  echo "→ Installazione PyTorch NVIDIA (${TORCH_WHEEL##*/})…"
  UV_SKIP_WHEEL_FILENAME_CHECK=1 "$PIP" install "$TORCH_WHEEL"
fi

"$PYTHON" -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"

echo "→ Installazione nano-parakeet…"
"$PIP" install -q "numpy<2"
"$PIP" install -q nano-parakeet --no-deps
"$PIP" install -q soundfile sentencepiece huggingface-hub

echo "→ Warm-up modello (download ~1.1 GB al primo avvio, CPU su Orin 8GB)…"
"$PYTHON" -c "
from nano_parakeet import from_pretrained
m = from_pretrained(device='cpu')
print('modello pronto su CPU:', type(m).__name__)
"

mkdir -p "${HOME}/.config/systemd/user"
if [ ! -f "$SERVICE_SRC" ]; then
  echo "File servizio mancante: $SERVICE_SRC" >&2
  exit 1
fi
cp -f "$SERVICE_SRC" "${HOME}/.config/systemd/user/karen-parakeet-asr.service"
systemctl --user daemon-reload

echo ""
echo "✓ Setup completato."
echo "  systemctl --user enable --now karen-parakeet-asr"
echo "  TOPGRO: asr.riva.http_url → http://192.168.1.96:9000/v1/audio/transcriptions"
