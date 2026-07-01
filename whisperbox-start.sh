#!/bin/bash
# Starts Whisperbox detached, so it keeps running after you close the window.
cd "$(dirname "$0")" || exit 1

# Don't stack duplicate instances (two would double-trigger the hotkey).
pkill -f "whisperbox_native.py" 2>/dev/null
sleep 1

source .venv/bin/activate
nohup python -u whisperbox_native.py >/tmp/whisperbox.log 2>&1 &
disown
PID=$!

echo ""
echo "  ✅ Whisperbox is running (pid $PID)."
echo "     It will KEEP running even if you close this window."
echo ""
echo "     Dictate : Ctrl + Shift + D   (talk, press again to stop)"
echo "     Quit    : Ctrl + Shift + Q"
echo "     Log     : /tmp/whisperbox.log"
echo ""
