#!/usr/bin/env bash
# nano-parakeet (CPU) su TOPGRO — STT locale, LLM resta su GPU.
#
# Uso:
#   bash scripts/setup_nano_parakeet_topgro.sh
#   systemctl --user enable --now karen-parakeet-asr
#   curl -s http://127.0.0.1:9000/v1/health/ready

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOST_DIR="${KAREN_HOST_DIR:-$(cd "$SCRIPT_DIR/../host" && pwd)}"
VENV="${HOST_DIR}/venv"
PYTHON="${VENV}/bin/python"
PIP="${VENV}/bin/pip"
SERVICE_SRC="${HOST_DIR}/systemd/karen-parakeet-asr.service"

if [ ! -x "$PYTHON" ]; then
  echo "venv non trovato: $VENV" >&2
  exit 1
fi

echo "=== nano-parakeet su TOPGRO (CPU) ==="
"$PIP" install -q --upgrade pip
"$PIP" install -q torch nano-parakeet

"$PYTHON" -c "
from nano_parakeet import from_pretrained
m = from_pretrained(device='cpu')
print('modello pronto su CPU')
"

mkdir -p "${HOME}/.config/systemd/user"
cp -f "$SERVICE_SRC" "${HOME}/.config/systemd/user/karen-parakeet-asr.service"
systemctl --user daemon-reload

echo ""
echo "✓ Setup completato."
echo "  systemctl --user enable --now karen-parakeet-asr"
echo "  asr.riva.http_url: http://127.0.0.1:9000/v1/audio/transcriptions"
