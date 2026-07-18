#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Karen – Setup TOPGRO (x86_64 + GTX 1650)
#  Eseguire come: bash scripts/setup_topgro.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

HOST_DIR="$(cd "$(dirname "$0")/.." && pwd)/host"
VENV_DIR="$HOST_DIR/venv"

echo "=== Karen Setup – TOPGRO (x86_64 CUDA) ==="
echo "Directory: $HOST_DIR"
echo ""

echo "[1/5] Pacchetti di sistema…"
sudo apt-get update -qq
sudo apt-get install -y \
    python3-pip python3-venv python3-dev \
    libsndfile1 ffmpeg git curl wget build-essential cmake \
    nvidia-cuda-toolkit iputils-ping

echo "[2/5] Virtual environment…"
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --upgrade pip wheel setuptools

echo "[3/5] llama-cpp-python (CUDA, sm_75 GTX 1650)…"
CMAKE_ARGS="-DLLAMA_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=75" \
  FORCE_CMAKE=1 \
  pip install llama-cpp-python --force-reinstall --no-cache-dir

echo "[4/5] faster-whisper + ctranslate2 (wheel CUDA x86_64)…"
pip install faster-whisper

echo "[5/5] Dipendenze rimanenti…"
pip install -r "$HOST_DIR/requirements.txt"

echo ""
echo "✓ Setup TOPGRO completato!"
echo ""
echo "Prossimi passi:"
echo "  1. bash scripts/install_models.sh"
echo "  2. cp host/config.yaml.example host/config.yaml   # token HA, IP ESP32"
echo "  3. export KAREN_PROFILE=topgro"
echo "  4. cd host && ../host/venv/bin/python main.py"
echo "  5. bash host/scripts/install_systemd.sh topgro"
