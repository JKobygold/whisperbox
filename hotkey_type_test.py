#!/usr/bin/env python3
"""
TEST 4 — the whole thing: hotkey records, transcribes, and TYPES the text
into whatever text field your cursor is in.

Ctrl+Shift+D -> START recording
Ctrl+Shift+D -> STOP, transcribe, and type the words at your cursor
Esc to quit.

Before recording: click into a text field (a note, a browser box, this chat).
"""
import time
import numpy as np
import sounddevice as sd
from pynput import keyboard
from faster_whisper import WhisperModel

LOG = ("/private/tmp/claude-501/-Users-Darthmaul2/"
       "dd0ceecc-e0ee-4fb5-9203-c2310423c1af/scratchpad/hotkey_type_test.log")

CTRLS = {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
SHIFTS = {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}
D_VK = 2
SR = 16000

kb = keyboard.Controller()


def w(msg):
    line = f"{time.strftime('%H:%M:%S')}  {msg}"
    with open(LOG, "a") as f:
        f.write(line + "\n")
    print(line, flush=True)


open(LOG, "w").close()
w("TEST 4: loading Whisper model (small.en)...")
model = WhisperModel("small.en", device="cpu", compute_type="int8")
w("Model ready. ==> Click a text field, Ctrl+Shift+D to record, again to type. Esc quits. <==")

mods = {"ctrl": False, "shift": False}
d_down = {"v": False}
stream = {"s": None}
frames = []


def audio_cb(indata, n, t, status):
    frames.append(indata.copy())


def type_text(text):
    try:
        kb.type(text)
        w(f"    typed at cursor: {text!r}")
    except Exception as e:
        w(f"    !! TYPING FAILED (Accessibility permission?): {e!r}")


def transcribe_and_type(audio):
    if audio.size == 0:
        w(">>> (no audio)")
        return
    w(f"    transcribing {audio.size / SR:.1f}s...")
    segments, _ = model.transcribe(audio, language="en", beam_size=5)
    text = " ".join(s.text.strip() for s in segments).strip()
    if not text:
        w(">>> (empty transcript)")
        return
    w(f">>> TRANSCRIPT: {text!r}")
    type_text(" " + text)   # leading space so it appends cleanly


def toggle():
    if stream["s"] is None:
        frames.clear()
        stream["s"] = sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                                     blocksize=1600, callback=audio_cb)
        stream["s"].start()
        w("=== RECORDING — speak now ===")
    else:
        stream["s"].stop(); stream["s"].close(); stream["s"] = None
        w("=== STOPPED ===")
        audio = (np.concatenate(frames).flatten() if frames
                 else np.zeros(0, dtype="float32"))
        transcribe_and_type(audio)


def on_press(k):
    if k in CTRLS:
        mods["ctrl"] = True
    elif k in SHIFTS:
        mods["shift"] = True
    elif k == keyboard.Key.esc:
        if stream["s"] is not None:
            stream["s"].stop(); stream["s"].close()
        w("Esc — quitting.")
        return False
    else:
        if getattr(k, "vk", None) == D_VK:
            if mods["ctrl"] and mods["shift"] and not d_down["v"]:
                d_down["v"] = True
                toggle()


def on_release(k):
    if k in CTRLS:
        mods["ctrl"] = False
    elif k in SHIFTS:
        mods["shift"] = False
    elif getattr(k, "vk", None) == D_VK:
        d_down["v"] = False


with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
    l.join()

w("TEST 4 finished.")
