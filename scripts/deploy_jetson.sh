#!/usr/bin/env bash
# Deploy sicuro su Jetson Orin: test → copia file → pip → restart → verifica porta.
set -euo pipefail

REMOTE="${KAREN_REMOTE:-donat@192.168.1.96}"
REMOTE_HOST="${REMOTE#*@}"
REMOTE_DIR="${KAREN_REMOTE_DIR:-karen/jetson}"
PROFILE="${KAREN_PROFILE:-jetson}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="$ROOT/host"

echo "=== Test parser intent ==="
python3 "$ROOT/tests/test_intent_parsers.py"

echo "=== Deploy → $REMOTE:$REMOTE_DIR ==="
ssh "$REMOTE" "mkdir -p ~/karen/tests ~/$REMOTE_DIR/scripts"
tar czf /tmp/karen-jetson.tgz \
  --exclude='venv' --exclude='models' --exclude='__pycache__' \
  --exclude='*.log' --exclude='data' --exclude='config.yaml' \
  -C "$HOST" .
scp /tmp/karen-jetson.tgz "$REMOTE:/tmp/karen-jetson.tgz"
scp "$ROOT/tests/test_intent_parsers.py" "$REMOTE:~/karen/tests/test_intent_parsers.py"
scp "$ROOT/scripts/test_asr_backends.py" "$REMOTE:~/karen/jetson/scripts/test_asr_backends.py"
scp "$ROOT/scripts/setup_riva_parakeet_jetson.sh" "$REMOTE:~/karen/jetson/scripts/setup_riva_parakeet_jetson.sh"

ssh "$REMOTE" "set -e
  BACKUP=/tmp/karen-jetson-config.yaml.bak
  test -f ~/$REMOTE_DIR/config.yaml && cp ~/$REMOTE_DIR/config.yaml \"\$BACKUP\"
  cd ~/$REMOTE_DIR
  tar xzf /tmp/karen-jetson.tgz
  rm /tmp/karen-jetson.tgz
  test -f \"\$BACKUP\" && cp \"\$BACKUP\" config.yaml
  mkdir -p ~/karen/tests
  ./venv/bin/pip install -q -r requirements.txt
  ./venv/bin/pip install -q nvidia-riva-client requests
  systemctl --user daemon-reload
  systemctl --user restart karen-$PROFILE
"

echo "=== Attendo porta 7001 (caricamento modelli ~60 s) ==="
for _ in $(seq 1 45); do
  if ssh "$REMOTE" "ss -ulnp 2>/dev/null | grep -q ':7001'"; then
    echo "✓ Jarvis attivo su $REMOTE_HOST:7001"
    ssh "$REMOTE" "loginctl show-user \$(whoami) -p Linger --value; tail -8 ~/$REMOTE_DIR/karen.log"
    exit 0
  fi
  sleep 2
done

echo "✗ Porta 7001 non in ascolto" >&2
ssh "$REMOTE" "tail -25 ~/$REMOTE_DIR/karen.log" >&2 || true
exit 1
