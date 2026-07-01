#!/bin/bash
# Starts the recording indicator (separate, non-activating Cocoa panel).
# Safe to start/stop anytime; it never touches dictation.
cd "$(dirname "$0")" || exit 1
pkill -f "whisperbox_indicator.py" 2>/dev/null
sleep 0.5
source .venv/bin/activate
nohup python -u whisperbox_indicator.py >/tmp/whisperbox_indicator.log 2>&1 &
disown
echo "  ✨ Indicator started (pid $!). Quit it: pkill -f whisperbox_indicator.py"
