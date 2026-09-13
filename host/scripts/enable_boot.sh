#!/usr/bin/env bash
# Abilita karen-{jetson|topgro} al boot (servizio utente) — richiede sudo una volta.
set -euo pipefail
PROFILE="${1:-topgro}"

sudo loginctl enable-linger "${USER}"
echo "✓ Linger abilitato per ${USER}: Jarvis (karen-${PROFILE}) resterà attivo senza login SSH."

if systemctl --user is-enabled "karen-${PROFILE}.service" 2>/dev/null; then
  systemctl --user restart "karen-${PROFILE}.service"
  echo "✓ Servizio karen-${PROFILE} riavviato."
else
  echo "⚠ Servizio non ancora installato. Esegui:"
  echo "  bash ~/karen/host/scripts/install_systemd.sh ${PROFILE}"
fi

echo
echo "Verifica:"
echo "  loginctl show-user ${USER} -p Linger"
echo "  systemctl --user is-active karen-${PROFILE}"
echo "  ss -ulnp | grep 7001"
