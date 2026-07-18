#!/usr/bin/env bash
# Avvia Karen con le librerie CUDA/OpenBLAS nel path.
export LD_LIBRARY_PATH="${HOME}/.local/lib:/usr/lib/aarch64-linux-gnu/openblas-pthread:/usr/local/cuda/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="/usr/local/cuda/bin:${PATH}"
cd "$(dirname "$0")/.."
exec python3 main.py "$@"
