#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
exec python -u stt.py >/tmp/whisperbox_cli.log 2>&1
