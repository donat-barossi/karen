#!/usr/bin/env bash
# Abilita karen-{jetson|topgro} al boot (servizio utente) — richiede sudo una volta.
set -euo pipefail
PROFILE="${1:-jetson}"

sudo loginctl enable-linger "${USER}"
echo "✓ Linger abilitato per ${USER}: karen-${PROFILE} partirà al boot anche senza login."
systemctl --user is-enabled "karen-${PROFILE}.service" 2>/dev/null \
  || echo "Prima esegui: bash ~/karen/host/scripts/install_systemd.sh ${PROFILE}"
