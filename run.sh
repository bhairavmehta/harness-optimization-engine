#!/usr/bin/env bash
# Start the Harness Optimization Engine on http://localhost:8000
set -e
cd "$(dirname "$0")"
python3 -m pip install -q -r requirements.txt
exec python3 -m uvicorn backend.app:app --host 0.0.0.0 --port "${PORT:-8000}" "$@"
