#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
exec python hotkey_type_test.py
