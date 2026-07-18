#!/usr/bin/env bash
# Pubblica il progetto sul repository GitHub *karen* (non karen_old).
#
# Prerequisito su GitHub (una tantum):
#   1. Rinomina o elimina il vecchio repo "karen_old" se il nome "karen" non è libero
#   2. Crea un repository VUOTO chiamato "karen" (senza README/.gitignore)
#
# Poi esegui:
#   bash scripts/publish_karen_repo.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE="${KAREN_REMOTE:-git@github.com:donat-barossi/karen.git}"

cd "$ROOT"

if git ls-remote "$REMOTE" >/dev/null 2>&1; then
    refs="$(git ls-remote "$REMOTE" | wc -l)"
    if [[ "$refs" -gt 0 ]]; then
        echo "⚠  $REMOTE esiste già e contiene commit."
        echo "   Se punta ancora a karen_old, rinomina quel repo su GitHub prima di continuare."
        read -r -p "Continuo comunque? [y/N] " ans
        [[ "${ans,,}" == "y" ]] || exit 1
    fi
else
    echo "❌ Repository non trovato: $REMOTE"
    echo "   Crea prima il repo vuoto 'karen' su GitHub."
    exit 1
fi

git remote set-url origin "$REMOTE"

# Assicura branch principali
git checkout main
git merge feature/gaming-pc-migration -m "Merge feature/gaming-pc-migration into main" 2>/dev/null || true

echo "→ Push main..."
git push -u origin main

echo "→ Push feature/gaming-pc-migration..."
git push -u origin feature/gaming-pc-migration

echo "✓ Pubblicato su $REMOTE"
echo "  main: https://github.com/donat-barossi/karen/tree/main"
echo "  feature/gaming-pc-migration: https://github.com/donat-barossi/karen/tree/feature/gaming-pc-migration"
