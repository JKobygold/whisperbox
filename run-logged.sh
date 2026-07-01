#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
exec python -u gui.py >/tmp/whisperbox_app.log 2>&1
