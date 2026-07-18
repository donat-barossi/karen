#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Karen – Download modelli AI
#  Whisper (CTranslate2) + Phi-3 Mini GGUF + Piper voce italiana
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

HOST_DIR="${KAREN_HOST_DIR:-$(cd "$(dirname "$0")/.." && pwd)/host}"
MODELS_DIR="$HOST_DIR/models"
mkdir -p "$MODELS_DIR"

echo "=== Karen – Download modelli AI ==="
echo "Destinazione: $MODELS_DIR"
echo ""

# ── 1. Whisper small (CTranslate2 format per faster-whisper) ─────────────────
echo "[1/3] Whisper small (CTranslate2)…"
WHISPER_DIR="$MODELS_DIR/whisper-small-ct2"
if [ -d "$WHISPER_DIR" ]; then
    echo "      → già presente, skip."
else
    pip install huggingface_hub -q
    python3 - <<'EOF'
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="guillaumekln/faster-whisper-small",
    local_dir="__WHISPER_DIR__",
    ignore_patterns=["*.msgpack", "*.h5"],
)
EOF
    # Sostituisci placeholder con percorso reale
    python3 -c "
import subprocess, os
path = os.environ.get('WHISPER_DIR_ENV', '')
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id='guillaumekln/faster-whisper-small',
    local_dir='$WHISPER_DIR',
    ignore_patterns=['*.msgpack', '*.h5'],
)
print('Whisper scaricato in $WHISPER_DIR')
"
fi

# ── 2. Phi-3 Mini 4K Instruct Q4_K_M (GGUF) ──────────────────────────────────
echo "[2/3] Phi-3 Mini 4K Q4_K_M GGUF (~2.4 GB)…"
PHI3_FILE="$MODELS_DIR/phi3-mini-4k-q4_k_m.gguf"
if [ -f "$PHI3_FILE" ]; then
    echo "      → già presente, skip."
else
    wget -q --show-progress \
        "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf" \
        -O "$PHI3_FILE"
    echo "      ✓ Phi-3 Mini scaricato"
fi

# ── 3. Piper – voce italiana paola-medium ─────────────────────────────────────
echo "[3/3] Piper TTS – voce it_IT-paola-medium…"
PIPER_ONNX="$MODELS_DIR/it_IT-paola-medium.onnx"
PIPER_JSON="$MODELS_DIR/it_IT-paola-medium.onnx.json"
PIPER_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/it/it_IT/paola/medium"

if [ -f "$PIPER_ONNX" ]; then
    echo "      → già presente, skip."
else
    wget -q --show-progress "$PIPER_BASE/it_IT-paola-medium.onnx"     -O "$PIPER_ONNX"
    wget -q --show-progress "$PIPER_BASE/it_IT-paola-medium.onnx.json" -O "$PIPER_JSON"
    echo "      ✓ Piper voce italiana scaricata"
fi

echo ""
echo "✓ Tutti i modelli pronti in $MODELS_DIR"
du -sh "$MODELS_DIR"/*
