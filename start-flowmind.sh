#!/usr/bin/env bash
# FlowMind — AI Business Consultant MVP (macOS / Linux)
set -e
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt --quiet --disable-pip-version-check
echo
echo "  FlowMind app       http://localhost:8000"
echo "  Guided test        http://localhost:8000/demo"
echo "  Pilot results      http://localhost:8000/pilot-results"
echo
exec python3 -m uvicorn server.app:app --port 8000 --host 127.0.0.1
