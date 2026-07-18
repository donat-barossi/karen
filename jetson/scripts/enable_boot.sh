#!/usr/bin/env bash
# Abilita karen-jetson al boot (servizio utente) — richiede sudo una sola volta.
set -euo pipefail
sudo loginctl enable-linger "${USER}"
echo "✓ Linger abilitato per ${USER}: karen-jetson partirà al boot anche senza login."
systemctl --user is-enabled karen-jetson.service 2>/dev/null || echo "Prima esegui: bash ~/karen/jetson/scripts/install_systemd.sh"
