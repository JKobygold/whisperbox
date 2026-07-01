#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
exec python -m unittest -v test_whisperbox
