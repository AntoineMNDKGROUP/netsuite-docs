#!/usr/bin/env bash
# Helper pour lancer l'extractor depuis le terminal Mac.
# Usage:
#   ./bin/run.sh ping             # test connexion
#   ./bin/run.sh extract          # extraction complète (scripts + custom fields)
#   ./bin/run.sh extract --no-fields  # uniquement les scripts
set -euo pipefail

cd "$(dirname "$0")/.."

# 1. venv (créé si absent ou incomplet)
if [ ! -f ".venv/bin/activate" ]; then
  echo "→ Création du venv..."
  rm -rf .venv
  python3 -m venv .venv
fi

# 2. activation
# shellcheck disable=SC1091
source .venv/bin/activate

# 3. installation des deps si pas déjà fait
if ! python -c "import requests, dotenv, supabase, requests_oauthlib" 2>/dev/null; then
  echo "→ Installation des dépendances..."
  pip install -q --upgrade pip
  pip install -q -r requirements.txt
fi

# 4. lancement
exec python -m src.main "$@"
