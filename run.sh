#!/bin/bash
# Starts the speech-to-text app (graphical window).
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "No virtualenv found. Running setup first..."
  ./setup.sh
fi
source .venv/bin/activate
exec python gui.py
