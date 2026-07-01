#!/usr/bin/env python3
"""
INTEGRATION TEST — the real HotkeyManager + the real global listener.

This is the layer the unit tests mocked. It wires the ACTUAL HotkeyManager to a
fake core that just logs, so we can see whether pressing the real Ctrl+Shift+D
actually triggers 'toggle' through the real key objects.

Press Ctrl+Shift+D a few times, then Ctrl+Shift+Q to quit.
"""
import threading
import time

import core

LOG = ("/private/tmp/claude-501/-Users-Darthmaul2/"
       "dd0ceecc-e0ee-4fb5-9203-c2310423c1af/scratchpad/hotkey_integration.log")


def w(msg):
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    with open(LOG, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


open(LOG, "w").close()
cfg = core.load_config()
w(f"INTEGRATION TEST — mode={cfg['mode']} hotkey={cfg['hotkey']} "
  f"quit={cfg['quit_hotkey']}")


class FakeCore:
    model = "loaded"

    def start_recording(self):
        w(">>> start_recording()  (HOTKEY WORKS)")

    def stop_recording(self):
        w(">>> stop_recording()")

    def toggle(self):
        w(">>> TOGGLE fired  (HOTKEY WORKS)")


stop = threading.Event()
mgr = core.HotkeyManager(
    cfg, FakeCore(),
    on_quit=lambda: (w("quit hotkey -> exiting"), stop.set()),
    on_window=lambda: w("window hotkey fired"))
mgr.start()
w("Listening. ==> Press Ctrl+Shift+D a few times, then Ctrl+Shift+Q to quit. <==")
stop.wait()
mgr.stop()
w("done.")
