#!/bin/bash
# Imposta il mixer ALSA prima che Music Assistant apra la scheda audio.
# Su molte schede Realtek il controllo Master parte muto (0%) → nessun suono.

set -euo pipefail

CARD="${ALSA_CARD:-1}"

if ! command -v amixer >/dev/null 2>&1; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq alsa-utils >/dev/null
fi

amixer -c "$CARD" sset Master 100% unmute || true
amixer -c "$CARD" sset Headphone 100% unmute || true
amixer -c "$CARD" sset Front 100% unmute || true
amixer -c "$CARD" cset name='Auto-Mute Mode' Disabled 2>/dev/null || true

echo "ALSA card $CARD ready (Master unmuted)"
