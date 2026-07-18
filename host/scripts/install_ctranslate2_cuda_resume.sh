#!/usr/bin/env bash
# Riprende install CTranslate2 CUDA se la build C++ è ok ma fallisce il CLI (OpenBLAS).
set -euo pipefail

export PATH="/usr/local/cuda/bin:${PATH}"
export LD_LIBRARY_PATH="/usr/local/cuda/lib64:/usr/lib/aarch64-linux-gnu/openblas-pthread:${LD_LIBRARY_PATH:-}"

INSTALL_PREFIX="${INSTALL_PREFIX:-$HOME/.local}"
BUILD_DIR="${BUILD_DIR:-/tmp/CTranslate2-build}"
OPENBLAS_DIR="/usr/lib/aarch64-linux-gnu/openblas-pthread"

if [[ ! -f "$BUILD_DIR/libctranslate2.so.4.6.0" ]]; then
    echo "Libreria non trovata in $BUILD_DIR — esegui prima install_ctranslate2_cuda.sh"
    exit 1
fi

echo "=== Resume install CTranslate2 (lib già compilata) ==="

mkdir -p "$INSTALL_PREFIX/lib"
cp -a "$BUILD_DIR"/libctranslate2.so* "$INSTALL_PREFIX/lib/"

# ldconfig richiede sudo; usiamo LD_LIBRARY_PATH (Karen lo eredita all'avvio)
export LD_LIBRARY_PATH="$INSTALL_PREFIX/lib:$OPENBLAS_DIR:/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}"

# Opzionale (con sudo): rende le lib visibili a tutto il sistema
if sudo -n true 2>/dev/null; then
    echo "$OPENBLAS_DIR" | sudo tee /etc/ld.so.conf.d/openblas-pthread.conf >/dev/null
    echo "$INSTALL_PREFIX/lib" | sudo tee /etc/ld.so.conf.d/ctranslate2-local.conf >/dev/null
    sudo ldconfig
else
    echo "Nota: sudo non disponibile — uso LD_LIBRARY_PATH (ok per Karen via nohup/systemd)"
    grep -q 'openblas-pthread' "$HOME/.bashrc" 2>/dev/null || \
        echo 'export LD_LIBRARY_PATH="$HOME/.local/lib:/usr/lib/aarch64-linux-gnu/openblas-pthread:/usr/local/cuda/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"' >> "$HOME/.bashrc"
fi

cd /tmp/CTranslate2/python
pip3 install -r install_requirements.txt
pip3 install --no-build-isolation --force-reinstall .

python3 - <<'PY'
import ctranslate2
n = ctranslate2.get_cuda_device_count()
print(f"CTranslate2 {ctranslate2.__version__} | CUDA devices: {n}")
if n == 0:
    raise SystemExit("CUDA non rilevata")
PY

echo "=== OK: CTranslate2 CUDA installato ==="
echo "Avvia Karen con: bash ~/karen/host/scripts/start_karen.sh"
