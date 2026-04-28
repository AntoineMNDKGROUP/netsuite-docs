#!/usr/bin/env bash
# Helper pour lancer un module debug.
# Usage: ./bin/debug.sh meta customer
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f ".venv/bin/activate" ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import requests, dotenv, supabase, requests_oauthlib" 2>/dev/null; then
  pip install -q --upgrade pip
  pip install -q -r requirements.txt
fi

cmd="${1:-meta}"
shift || true

case "$cmd" in
  meta)
    exec python -m src.debug_meta "$@"
    ;;
  file)
    exec python -m src.debug_file "$@"
    ;;
  *)
    echo "Usage: ./bin/debug.sh meta <record_type>"
    echo "       ./bin/debug.sh file <file_id>"
    exit 1
    ;;
esac
