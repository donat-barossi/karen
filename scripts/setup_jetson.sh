#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Karen – Setup Jetson Orin Nano
#  Installa dipendenze sistema + Python venv
#  Eseguire come: bash setup_jetson.sh
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

HOST_DIR="$(cd "$(dirname "$0")/.." && pwd)/host"
VENV_DIR="$HOST_DIR/venv"

echo "=== Karen Setup – Jetson Orin Nano ==="
echo "Directory: $HOST_DIR"
echo ""

# ── 1. Pacchetti di sistema ────────────────────────────────────────────────
echo "[1/5] Installazione pacchetti di sistema…"
sudo apt-get update -qq
sudo apt-get install -y \
    python3-pip python3-venv python3-dev \
    libsndfile1 libportaudio2 ffmpeg \
    git curl wget build-essential cmake \
    nvidia-cuda-toolkit

# ── 2. Python venv ────────────────────────────────────────────────────────
echo "[2/5] Creazione virtual environment Python…"
python3 -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --upgrade pip wheel setuptools

# ── 3. llama-cpp-python con CUDA ──────────────────────────────────────────
echo "[3/5] Installazione llama-cpp-python (CUDA)…"
echo "      Questo richiede alcuni minuti (compilazione da sorgente)."
CMAKE_ARGS="-DLLAMA_CUDA=on" \
  FORCE_CMAKE=1 \
  pip install llama-cpp-python --force-reinstall --no-cache-dir

# ── 4. faster-whisper ──────────────────────────────────────────────────────
echo "[4/5] Installazione faster-whisper…"
pip install faster-whisper

# ── 5. Resto delle dipendenze ──────────────────────────────────────────────
echo "[5/5] Installazione dipendenze rimanenti…"
pip install -r "$HOST_DIR/requirements.txt"

echo ""
echo "✓ Setup completato!"
echo ""
echo "Prossimi passi:"
echo "  1. bash scripts/install_models.sh"
echo "  2. cp host/config.yaml.example host/config.yaml   # token HA, IP ESP32"
echo "  3. export KAREN_PROFILE=jetson"
echo "  4. cd host && ../host/venv/bin/python main.py"
echo "  5. bash host/scripts/install_systemd.sh jetson"
echo ""
echo "Whisper CUDA su Jetson (opzionale): host/scripts/install_ctranslate2_cuda.sh"
