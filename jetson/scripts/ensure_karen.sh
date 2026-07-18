#!/usr/bin/env bash
# Avvia Karen in background se non è già in esecuzione.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="${ROOT}/karen.log"
PIDFILE="${ROOT}/.karen.pid"

if ss -ulnp 2>/dev/null | grep -q ':7001'; then
    echo "Karen già attiva (porta 7001 in ascolto)"
    exit 0
fi

if [[ -f "$PIDFILE" ]]; then
    old_pid="$(cat "$PIDFILE")"
    if kill -0 "$old_pid" 2>/dev/null; then
        echo "Karen già attiva (PID $old_pid)"
        exit 0
    fi
fi

cd "$ROOT"
nohup bash scripts/start_karen.sh >>"$LOG" 2>&1 &
echo $! >"$PIDFILE"
echo "Karen avviata (PID $(cat "$PIDFILE"), log: $LOG)"
