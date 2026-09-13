#!/usr/bin/env bash
# Parakeet 1.1B multilingual NIM — solo locale su Jetson Orin (ARM64).
# L'inferenza resta sul dispositivo; NGC_API_KEY serve SOLO al pull dell'immagine Docker.
#
# Uso sul Jetson:
#   export NGC_API_KEY=...    # ngc.nvidia.com → Setup → Generate API Key
#   bash scripts/setup_riva_parakeet_jetson.sh
#   curl -s http://127.0.0.1:9000/v1/health/ready
#
# Test ASR:
#   python scripts/test_asr_backends.py --audio prova.wav
#
# Ferma Karen sul Jetson prima (GPU condivisa):
#   systemctl --user stop karen-jetson

set -euo pipefail

CONTAINER="${RIVA_NIM_CONTAINER:-karen-parakeet-jetson}"
IMAGE="${RIVA_NIM_IMAGE:-nvcr.io/nim/nvidia/parakeet-1-1b-rnnt-multilingual:latest}"
HTTP_PORT="${RIVA_NIM_HTTP_PORT:-9000}"
GRPC_PORT="${RIVA_NIM_GRPC_PORT:-50051}"

if [[ -z "${NGC_API_KEY:-}" ]] && ! docker pull "$IMAGE" --dry-run >/dev/null 2>&1; then
  if ! grep -q nvcr.io ~/.docker/config.json 2>/dev/null; then
    echo "Serve NGC_API_KEY o 'docker login nvcr.io' (ngc.nvidia.com)." >&2
    exit 1
  fi
fi

if ! command -v docker >/dev/null; then
  echo "Docker non installato sul Jetson." >&2
  exit 1
fi

if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "Rimuovo container esistente $CONTAINER"
  docker rm -f "$CONTAINER"
fi

echo "=== Parakeet NIM su Jetson (HTTP $HTTP_PORT) ==="
echo "Primo avvio: download ~12 GB, attendere..."

docker run -d --name "$CONTAINER" \
  --runtime=nvidia --gpus all \
  --shm-size=8g \
  ${NGC_API_KEY:+-e NGC_API_KEY} \
  -e NIM_HTTP_API_PORT="$HTTP_PORT" \
  -e NIM_GRPC_API_PORT="$GRPC_PORT" \
  -e NIM_TAGS_SELECTOR="mode=offline,diarizer=disabled" \
  -p "${HTTP_PORT}:${HTTP_PORT}" \
  -p "${GRPC_PORT}:${GRPC_PORT}" \
  "$IMAGE"

echo "Attendo readiness (può richiedere diversi minuti al primo avvio)..."
for _ in $(seq 1 180); do
  if curl -sf "http://127.0.0.1:${HTTP_PORT}/v1/health/ready" >/dev/null 2>&1; then
    echo "✓ Parakeet pronto su http://127.0.0.1:${HTTP_PORT}"
    echo ""
    echo "Karen Jetson (config/jetson.yaml):"
    echo "  asr.backend: riva"
    echo "  asr.riva.http_url: http://127.0.0.1:${HTTP_PORT}/v1/audio/transcriptions"
    echo ""
    echo "Karen TOPGRO → ASR su Jetson via LAN:"
    echo "  asr.riva.http_url: http://192.168.1.96:${HTTP_PORT}/v1/audio/transcriptions"
    exit 0
  fi
  sleep 5
done

echo "✗ Timeout — ultime righe log:" >&2
docker logs "$CONTAINER" 2>&1 | tail -40
exit 1
