#!/usr/bin/env bash
# Installa karen-jetson come servizio systemd utente (no sudo).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_SRC="${ROOT}/systemd/karen-jetson.service"
USER_UNIT_DIR="${HOME}/.config/systemd/user"
SERVICE_DST="${USER_UNIT_DIR}/karen-jetson.service"

mkdir -p "$USER_UNIT_DIR"
cp "$SERVICE_SRC" "$SERVICE_DST"

echo "→ Arresto eventuale istanza manuale…"
systemctl --user stop karen-jetson.service 2>/dev/null || true
sleep 2

systemctl --user daemon-reload
systemctl --user enable karen-jetson.service
systemctl --user restart karen-jetson.service

echo "→ Attendo caricamento modelli (~60 s)…"
for i in $(seq 1 30); do
    if ss -ulnp 2>/dev/null | grep -q ':7001'; then
        echo "✓ Karen attiva (porta 7001, servizio utente)"
        systemctl --user status karen-jetson.service --no-pager -l | head -15
        echo
        echo "Comandi utili:"
        echo "  systemctl --user status karen-jetson"
        echo "  systemctl --user restart karen-jetson"
        echo "  tail -f ${ROOT}/karen.log"
        echo
        echo "Per avvio automatico al boot (una tantum, richiede sudo):"
        echo "  sudo loginctl enable-linger ${USER}"
        exit 0
    fi
    sleep 2
done

echo "⚠ Porta 7001 non in ascolto. Log:" >&2
systemctl --user status karen-jetson.service --no-pager -l | head -20
tail -20 "${ROOT}/karen.log" >&2 || true
exit 1
