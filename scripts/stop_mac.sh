#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose stop
echo 'Database stopped. Stop FastAPI with Ctrl+C in its terminal.'
