#!/usr/bin/env bash
# FastConformer Italian-only (ONNX CPU) su TOPGRO — STT locale, LLM resta su GPU.
#
# Uso:
#   bash scripts/setup_fastconformer_topgro.sh
#   systemctl --user stop karen-parakeet-asr   # se attivo
#   systemctl --user enable --now karen-fastconformer-asr
#   curl -s http://127.0.0.1:9000/v1/health/ready

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOST_DIR="${KAREN_HOST_DIR:-$(cd "$SCRIPT_DIR/../host" && pwd)}"
VENV="${HOST_DIR}/venv"
PYTHON="${VENV}/bin/python"
PIP="${VENV}/bin/pip"
SERVICE_SRC="${HOST_DIR}/systemd/karen-fastconformer-asr.service"
MODEL="${FASTCONFORMER_MODEL:-OpenVoiceOS/stt_it_fastconformer_hybrid_large_pc_onnx}"

if [ ! -x "$PYTHON" ]; then
  echo "venv non trovato: $VENV" >&2
  exit 1
fi

echo "=== FastConformer IT su TOPGRO (ONNX CPU) ==="
"$PIP" install -q --upgrade pip
"$PIP" install -q "onnx-asr[cpu,hub]"

"$PYTHON" -c "
import onnx_asr
m = onnx_asr.load_model('${MODEL}')
print('modello pronto:', m)
"

mkdir -p "${HOME}/.config/systemd/user"
cp -f "$SERVICE_SRC" "${HOME}/.config/systemd/user/karen-fastconformer-asr.service"
systemctl --user daemon-reload

echo ""
echo "✓ Setup completato."
echo "  systemctl --user stop karen-parakeet-asr 2>/dev/null || true"
echo "  systemctl --user enable --now karen-fastconformer-asr"
echo "  asr.riva.http_url: http://127.0.0.1:9000/v1/audio/transcriptions"
