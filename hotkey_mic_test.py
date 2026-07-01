#!/usr/bin/env python3
"""
TEST 2 — does the hotkey turn the microphone ON and OFF?

Builds on Test 1 (which proved detection works). Now Ctrl+Shift+D toggles the
mic. While the mic is ON you'll see live audio levels, so we confirm it's
actually capturing your voice. Still NO transcription or typing yet.

Press Ctrl+Shift+D  -> MIC ON  (speak, watch the levels move)
Press Ctrl+Shift+D  -> MIC OFF
Press Esc to quit.
"""
import time
import numpy as np
import sounddevice as sd
from pynput import keyboard

LOG = ("/private/tmp/claude-501/-Users-Darthmaul2/"
       "dd0ceecc-e0ee-4fb5-9203-c2310423c1af/scratchpad/hotkey_mic_test.log")

CTRLS = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
SHIFTS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}
D_VK = 2


def w(msg):
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    with open(LOG, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


open(LOG, "w").close()
w("TEST 2 running.  ==> Ctrl+Shift+D toggles the mic. Esc to quit. <==")

mods = {"ctrl": False, "shift": False}
d_down = {"v": False}
stream = {"s": None}
cbcount = {"n": 0}


def audio_cb(indata, frames, t, status):
    lvl = float(np.sqrt(np.mean(np.square(indata))))
    cbcount["n"] += 1
    if cbcount["n"] % 10 == 0:            # ~once per second
        bar = "#" * int(min(1.0, lvl * 20) * 30)
        w(f"    mic level: {lvl:.3f} |{bar}")


def toggle_mic():
    if stream["s"] is None:
        stream["s"] = sd.InputStream(samplerate=16000, channels=1,
                                     dtype="float32", blocksize=1600,
                                     callback=audio_cb)
        stream["s"].start()
        w("=== MIC ON  — speak now, you should see levels ===")
    else:
        stream["s"].stop()
        stream["s"].close()
        stream["s"] = None
        w("=== MIC OFF ===")


def on_press(k):
    if k in CTRLS:
        mods["ctrl"] = True
    elif k in SHIFTS:
        mods["shift"] = True
    elif k == keyboard.Key.esc:
        if stream["s"] is not None:
            stream["s"].stop(); stream["s"].close()
        w("Esc pressed — quitting.")
        return False
    else:
        vk = getattr(k, "vk", None)
        if vk == D_VK:
            if mods["ctrl"] and mods["shift"] and not d_down["v"]:
                d_down["v"] = True          # ignore key auto-repeat
                toggle_mic()


def on_release(k):
    if k in CTRLS:
        mods["ctrl"] = False
    elif k in SHIFTS:
        mods["shift"] = False
    elif getattr(k, "vk", None) == D_VK:
        d_down["v"] = False


with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
    l.join()

w("TEST 2 finished.")
