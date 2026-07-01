#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
echo "Key test running. Press F9 a few times, then type: hello"
echo "Leave this window open, then tell Claude you're done."
exec python keytest.py
