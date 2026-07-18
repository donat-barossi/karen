#!/usr/bin/env bash
# Avvia Karen con librerie CUDA nel path (Jetson aarch64 o TOPGRO x86_64).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export KAREN_PROFILE="${KAREN_PROFILE:-jetson}"

ARCH="$(uname -m)"
CUDA_LIB="/usr/local/cuda/lib64"
USER_LIB="${HOME}/.local/lib"

if [ "$ARCH" = "aarch64" ]; then
  export LD_LIBRARY_PATH="${USER_LIB}:/usr/lib/aarch64-linux-gnu/openblas-pthread:${CUDA_LIB}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
else
  export LD_LIBRARY_PATH="${USER_LIB}:${CUDA_LIB}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
export PATH="/usr/local/cuda/bin:${PATH}"

cd "$ROOT"

PYTHON="${ROOT}/venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON=python3
fi

exec "$PYTHON" main.py "$@"
