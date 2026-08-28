#!/usr/bin/env bash
# Avvia l'API in sviluppo (hot reload) su http://localhost:8000
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install -q -r requirements.txt
exec ./.venv/bin/uvicorn app.main:app --reload --port 8000
