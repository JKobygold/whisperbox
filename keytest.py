#!/usr/bin/env python3
"""Diagnostic: logs every global key event the app can see, to a file."""
import time
from pynput import keyboard

LOG = "/private/tmp/claude-501/-Users-Darthmaul2/dd0ceecc-e0ee-4fb5-9203-c2310423c1af/scratchpad/keytest.log"


def w(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    with open(LOG, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


# reset log
open(LOG, "w").close()
w("=== keytest started — press keys now ===")

try:
    def on_press(k):
        w(f"PRESS   {k!r}")

    def on_release(k):
        w(f"RELEASE {k!r}")

    with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
        w("listener is running (if you see this and nothing else when typing, "
          "Input Monitoring is NOT granted)")
        l.join()
except Exception as e:
    w(f"LISTENER ERROR: {e!r}")
