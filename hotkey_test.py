#!/usr/bin/env python3
"""
TEST 1 — can we detect a hotkey and print when it's pressed?

Nothing else here: no microphone, no transcription, no typing. We just listen
globally for Ctrl+Shift+D and log every time it fires. Detection is by the D
key's hardware code (vk=2) plus modifier state, so Shift changing 'd'->'D'
doesn't matter.

Press Ctrl+Shift+D a few times, then press Esc to quit.
"""
import time
from pynput import keyboard

LOG = ("/private/tmp/claude-501/-Users-Darthmaul2/"
       "dd0ceecc-e0ee-4fb5-9203-c2310423c1af/scratchpad/hotkey_test.log")

CTRLS = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
SHIFTS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}
D_VK = 2   # hardware key code for the "D" key on a US layout


def w(msg):
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    with open(LOG, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


open(LOG, "w").close()
w("TEST 1 running.  ==> Press Ctrl+Shift+D a few times, then Esc to quit. <==")

mods = {"ctrl": False, "shift": False}
count = {"n": 0}


def on_press(k):
    if k in CTRLS:
        mods["ctrl"] = True
    elif k in SHIFTS:
        mods["shift"] = True
    elif k == keyboard.Key.esc:
        w("Esc pressed — quitting.")
        return False
    else:
        vk = getattr(k, "vk", None)
        if vk == D_VK and mods["ctrl"] and mods["shift"]:
            count["n"] += 1
            w(f">>> HOTKEY DETECTED: Ctrl+Shift+D  (fire #{count['n']}) <<<")


def on_release(k):
    if k in CTRLS:
        mods["ctrl"] = False
    elif k in SHIFTS:
        mods["shift"] = False


with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
    l.join()

w(f"TEST 1 finished. Total hotkey fires detected: {count['n']}")
