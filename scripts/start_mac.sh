#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v docker >/dev/null; then echo 'Install Docker Desktop first'; exit 1; fi
if ! command -v python3 >/dev/null; then echo 'Install Python 3.11/3.12 first'; exit 1; fi
docker compose up -d
cd backend
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; fi
echo 'Starting QuantBook AI at http://127.0.0.1:8000/docs'
python -m uvicorn app.main:app --reload
