#!/bin/bash
# One-time setup: creates a virtualenv and installs dependencies.
set -e
cd "$(dirname "$0")"

echo "Creating virtual environment (.venv)..."
python3 -m venv .venv
source .venv/bin/activate

echo "Upgrading pip..."
pip install --upgrade pip

echo "Installing dependencies..."
pip install -r requirements.txt

echo
echo "Setup complete. Run the app with:  ./run.sh"
