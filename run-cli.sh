#!/bin/bash
# Starts the speech-to-text app in the terminal (no window).
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "No virtualenv found. Running setup first..."
  ./setup.sh
fi
source .venv/bin/activate
exec python stt.py
