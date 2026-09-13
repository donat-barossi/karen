#!/usr/bin/env bash
# Deploy sicuro su TOPGRO: test → copia file → restart → verifica porta.
set -euo pipefail

REMOTE="${KAREN_REMOTE:-donat@192.168.1.33}"
REMOTE_HOST="${REMOTE#*@}"
REMOTE_DIR="${KAREN_REMOTE_DIR:-karen/host}"
PROFILE="${KAREN_PROFILE:-topgro}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="$ROOT/host"

echo "=== Test parser intent ==="
python3 "$ROOT/tests/test_intent_parsers.py"

echo "=== Deploy → $REMOTE:$REMOTE_DIR ==="
tar czf /tmp/karen-host.tgz -C "$HOST" karen config main.py requirements.txt scripts systemd
scp /tmp/karen-host.tgz "$REMOTE:/tmp/karen-host.tgz"
scp "$ROOT/tests/test_intent_parsers.py" "$REMOTE:~/karen/tests/test_intent_parsers.py"
scp "$ROOT/scripts/setup_fastconformer_topgro.sh" "$REMOTE:~/karen/scripts/setup_fastconformer_topgro.sh"

ssh "$REMOTE" "set -e
  cd ~/$REMOTE_DIR
  tar xzf /tmp/karen-host.tgz
  rm /tmp/karen-host.tgz
  ./venv/bin/pip install -q -r requirements.txt
  ./venv/bin/pip install -q requests tqdm scikit-learn
  mkdir -p ~/karen/tests ~/karen/scripts
  ./venv/bin/python ~/karen/tests/test_intent_parsers.py
  systemctl --user restart karen-$PROFILE
"

echo "=== Attendo porta 7001 ==="
for _ in $(seq 1 30); do
  if ssh "$REMOTE" "ss -ulnp 2>/dev/null | grep -q ':7001'"; then
    echo "✓ Jarvis attivo su $REMOTE_HOST:7001"
    ssh "$REMOTE" "loginctl show-user \$(whoami) -p Linger --value; tail -3 ~/$REMOTE_DIR/karen.log"
    exit 0
  fi
  sleep 2
done

echo "✗ Porta 7001 non in ascolto" >&2
ssh "$REMOTE" "tail -20 ~/$REMOTE_DIR/karen.log" >&2 || true
exit 1
