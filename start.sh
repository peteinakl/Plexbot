#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

if [ ! -d "frontend/dist" ]; then
  echo "Building frontend UI..."
  (cd frontend && npm install && npm run build)
fi

exec .venv/bin/python run.py --open "$@"
