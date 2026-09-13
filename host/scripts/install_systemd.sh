#!/usr/bin/env bash
# Installa Karen come servizio systemd utente (jetson | topgro).
set -euo pipefail

PROFILE="${1:-${KAREN_PROFILE:-jetson}}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_SRC="${ROOT}/systemd/karen-${PROFILE}.service"
USER_UNIT_DIR="${HOME}/.config/systemd/user"
SERVICE_NAME="karen-${PROFILE}.service"
SERVICE_DST="${USER_UNIT_DIR}/${SERVICE_NAME}"

if [ ! -f "$SERVICE_SRC" ]; then
  echo "Profilo sconosciuto: ${PROFILE}" >&2
  echo "Uso: bash install_systemd.sh [jetson|topgro]" >&2
  exit 1
fi

mkdir -p "$USER_UNIT_DIR"
cp "$SERVICE_SRC" "$SERVICE_DST"

echo "→ Arresto eventuale istanza manuale…"
systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
sleep 2

systemctl --user daemon-reload
systemctl --user enable "$SERVICE_NAME"
systemctl --user restart "$SERVICE_NAME"

echo "→ Attendo caricamento modelli (~60 s)…"
for _ in $(seq 1 30); do
    if ss -ulnp 2>/dev/null | grep -q ':7001'; then
        echo "✓ Karen attiva (profilo ${PROFILE}, porta 7001)"
        systemctl --user status "$SERVICE_NAME" --no-pager -l | head -15
        echo
        echo "Comandi utili:"
        echo "  systemctl --user status karen-${PROFILE}"
        echo "  systemctl --user restart karen-${PROFILE}"
        echo "  tail -f ${ROOT}/karen.log"
        echo "  tail -f ${ROOT}/esp32.log"
        echo
        LINGER=$(loginctl show-user "${USER}" -p Linger --value 2>/dev/null || echo "no")
        if [ "$LINGER" = "yes" ]; then
            echo "✓ Linger abilitato: Karen resta attiva senza sessione SSH."
        else
            echo "⚠ LINGER NON ABILITATO — Karen si ferma quando chiudi SSH!"
            echo "  Esegui una tantum: sudo loginctl enable-linger ${USER}"
            echo "  oppure: bash ${ROOT}/scripts/enable_boot.sh ${PROFILE}"
        fi
        echo
        echo "Per avvio automatico al boot (una tantum, richiede sudo):"
        echo "  sudo loginctl enable-linger ${USER}"
        exit 0
    fi
    sleep 2
done

echo "⚠ Porta 7001 non in ascolto. Log:" >&2
systemctl --user status "$SERVICE_NAME" --no-pager -l | head -20
tail -20 "${ROOT}/karen.log" >&2 || true
exit 1
