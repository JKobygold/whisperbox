#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
exec python "${1:-hotkey_test.py}"
