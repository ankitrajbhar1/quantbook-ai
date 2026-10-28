#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo 'Checking Docker Compose configuration...'
docker compose config --quiet
echo 'Checking database container...'
docker compose ps
echo 'Checking PostgreSQL readiness...'
docker compose exec db pg_isready -U quantbook -d quantbook
echo 'Checking tables...'
docker compose exec db psql -U quantbook -d quantbook -c '\dt'
echo 'All database checks completed.'
