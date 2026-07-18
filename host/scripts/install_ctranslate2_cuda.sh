#!/usr/bin/env bash
# Compila e installa CTranslate2 con CUDA su Jetson (JetPack 6 / Orin).
# I wheel PyPI per aarch64 sono CPU-only: faster-whisper non usa la GPU senza questo passo.
#
# Uso (sul Jetson):
#   cd ~/karen/host && bash scripts/install_ctranslate2_cuda.sh
#
# Tempo stimato: 20–40 minuti.

set -euo pipefail

export PATH="/usr/local/cuda/bin:${PATH}"
export LD_LIBRARY_PATH="/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}"

CT2_VERSION="${CT2_VERSION:-v4.6.0}"
INSTALL_PREFIX="${INSTALL_PREFIX:-$HOME/.local}"
CUDA_ARCH="${CUDA_ARCH:-87}"   # Jetson Orin (sm_87)
BUILD_DIR="${BUILD_DIR:-/tmp/CTranslate2-build}"
OPENBLAS_DIR="/usr/lib/aarch64-linux-gnu/openblas-pthread"

echo "=== CTranslate2 CUDA per Jetson Orin ==="
echo "Versione: $CT2_VERSION | CUDA arch: sm_${CUDA_ARCH}"

for cmd in cmake git python3 pip3; do
    command -v "$cmd" >/dev/null || { echo "Manca: $cmd"; exit 1; }
done
if ! command -v nvcc >/dev/null && [[ ! -x /usr/local/cuda/bin/nvcc ]]; then
    echo "Manca: nvcc (installa cuda-toolkit-12-6)"
    exit 1
fi

OPENBLAS_LIB="/usr/lib/aarch64-linux-gnu/openblas-pthread/libopenblas.so"
OPENBLAS_INC="/usr/include"

if ! dpkg -s libopenblas-dev >/dev/null 2>&1 || [[ ! -f "$OPENBLAS_LIB" ]]; then
    echo "Installa dipendenze: sudo apt install -y libopenblas-dev libopenblas0-pthread libcudnn9-dev-cuda-12 cmake build-essential git"
    exit 1
fi

pip3 uninstall -y ctranslate2 2>/dev/null || true

if [[ ! -d /tmp/CTranslate2/.git ]]; then
    git clone --recursive --depth 1 --branch "$CT2_VERSION" \
        https://github.com/OpenNMT/CTranslate2.git /tmp/CTranslate2
fi

rm -rf "$BUILD_DIR"
cmake -S /tmp/CTranslate2 -B "$BUILD_DIR" \
    -DWITH_CUDA=ON \
    -DWITH_CUDNN=ON \
    -DWITH_MKL=OFF \
    -DWITH_OPENBLAS=ON \
    -DOPENBLAS_LIBRARY="$OPENBLAS_LIB" \
    -DOPENBLAS_INCLUDE_DIR="$OPENBLAS_INC" \
    -DBUILD_CLI=OFF \
    -DOPENMP_RUNTIME=COMP \
    -DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCH" \
    -DCMAKE_INSTALL_PREFIX="$INSTALL_PREFIX" \
    -DCMAKE_INSTALL_RPATH="${OPENBLAS_DIR};/usr/local/cuda/lib64" \
    -DCMAKE_BUILD_TYPE=Release

cmake --build "$BUILD_DIR" -j"$(nproc)"
cmake --install "$BUILD_DIR"

# Aggiorna cache linker
echo "$OPENBLAS_DIR" | sudo tee /etc/ld.so.conf.d/openblas-pthread.conf >/dev/null
if [[ -d "$INSTALL_PREFIX/lib" ]]; then
    echo "$INSTALL_PREFIX/lib" | sudo tee /etc/ld.so.conf.d/ctranslate2-local.conf >/dev/null
    sudo ldconfig
fi

cd /tmp/CTranslate2/python
pip3 install -r install_requirements.txt
pip3 install --no-build-isolation --force-reinstall .

python3 - <<'PY'
import ctranslate2
n = ctranslate2.get_cuda_device_count()
print(f"CTranslate2 {ctranslate2.__version__} | CUDA devices: {n}")
if n == 0:
    raise SystemExit("CUDA non rilevata dopo installazione")
PY

echo "=== OK: CTranslate2 CUDA installato ==="
echo "Riavvia Karen: pkill -f 'python3 main.py'; cd ~/karen/host && nohup python3 main.py > karen.log 2>&1 &"
