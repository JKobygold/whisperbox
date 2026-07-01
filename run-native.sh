#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
exec python -u whisperbox_native.py >/tmp/whisperbox_native.log 2>&1
