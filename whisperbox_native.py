#!/usr/bin/env python3
"""
Whisperbox (native macOS build) — no pynput, no Tk. Crash-proof on macOS 26.

Every earlier crash was pynput calling the macOS input-source API
(TSMGetInputSourceProperty) off the main thread, which macOS 26 turns into a
hard crash. This build avoids that entirely:

  • Global hotkey  -> Quartz CGEventTap, reading only key codes + modifier flags
                      (never decodes characters, so it never calls TSM).
  • Typing         -> CGEventKeyboardSetUnicodeString, which inserts raw Unicode
                      with no keyboard-layout lookup (no TSM).

Windowless by design, so it never steals focus — text goes straight into the
field you're in. Ctrl+Shift+D to dictate, Ctrl+Shift+Q to quit (configurable).
"""
import collections
import json
import os
import threading
import time

try:
    import tkinter as tk
    _HAS_TK = True
except Exception:
    _HAS_TK = False

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from Quartz import (
    CFMachPortCreateRunLoopSource, CFRunLoopAddSource, CFRunLoopGetCurrent,
    CFRunLoopRun, kCFRunLoopCommonModes,
    CGEventCreateKeyboardEvent, CGEventGetFlags, CGEventGetIntegerValueField,
    CGEventKeyboardSetUnicodeString, CGEventPost, CGEventTapCreate,
    CGEventTapEnable, kCGEventTapOptionListenOnly, kCGHeadInsertEventTap,
    kCGHIDEventTap, kCGKeyboardEventKeycode, kCGSessionEventTap,
)

CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

cfg = {"hotkey": "<ctrl>+<shift>+d", "quit_hotkey": "<ctrl>+<shift>+q",
       "model": "small.en", "language": "en", "compute_type": "int8",
       "sample_rate": 16000, "output": "both", "insert_space": True,
       "sound_feedback": True,
       # System sound names from /System/Library/Sounds (Basso, Blow, Bottle,
       # Frog, Funk, Glass, Hero, Morse, Ping, Pop, Purr, Sosumi, Submarine,
       # Tink). Set to "" to silence that cue.
       "start_sound": "Tink", "stop_sound": "Pop", "done_sound": "Glass",
       "overlay": True}          # show the animated waveform pill while dictating
try:
    with open(CONFIG) as f:
        cfg.update({k: v for k, v in json.load(f).items() if v is not None})
except Exception as e:
    print(f"[native] config fallback: {e}", flush=True)

KEYCODES = {"a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7,
            "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
            "y": 16, "t": 17, "o": 31, "u": 32, "i": 34, "p": 35, "l": 37,
            "j": 38, "k": 40, "n": 45, "m": 46, "1": 18, "2": 19, "3": 20,
            "4": 21, "5": 23, "6": 22, "7": 26, "8": 28, "9": 25, "0": 29,
            "space": 49, "return": 36, "enter": 36, "tab": 48,
            "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
            "f7": 98, "f8": 100, "f9": 101}
MODMASK = {"shift": 0x20000, "ctrl": 0x40000, "control": 0x40000,
           "alt": 0x80000, "option": 0x80000, "cmd": 0x100000,
           "command": 0x100000}
MOD_BITS = 0x20000 | 0x40000 | 0x80000 | 0x100000
KEYDOWN, KEYUP, FLAGS = 10, 11, 12


def parse(spec):
    mods, kc = 0, None
    for tok in spec.split("+"):
        t = tok.strip().strip("<>").lower()
        if t in MODMASK:
            mods |= MODMASK[t]
        elif t in KEYCODES:
            kc = KEYCODES[t]
    return kc, mods


HK_KC, HK_MODS = parse(cfg["hotkey"])
Q_KC, Q_MODS = parse(cfg["quit_hotkey"])


def beep(name):
    if name and cfg.get("sound_feedback"):
        os.system(f"afplay /System/Library/Sounds/{name}.aiff >/dev/null 2>&1 &")


# ── native typing (no TSM / no layout lookup) ────────────────────────────────
def type_text(s):
    for ch in s:
        for down in (True, False):
            e = CGEventCreateKeyboardEvent(None, 0, down)
            CGEventKeyboardSetUnicodeString(e, len(ch), ch)
            CGEventPost(kCGHIDEventTap, e)
        time.sleep(0.003)


def copy_clip(s):
    try:
        import pyperclip
        pyperclip.copy(s)
    except Exception as e:
        print(f"[native] clipboard: {e}", flush=True)


# ── model ────────────────────────────────────────────────────────────────────
print(f"[native] hotkey kc={HK_KC} mods={hex(HK_MODS)} | loading model "
      f"'{cfg['model']}'...", flush=True)
model = WhisperModel(cfg["model"], device="cpu", compute_type=cfg["compute_type"])
print("[native] model ready", flush=True)

# ── recording / transcription (thread-safe) ──────────────────────────────────
st = {"down": False, "qdown": False}          # hotkey key-held flags
stop_event = threading.Event()
_lock = threading.Lock()                       # guards start/stop transitions
_model_lock = threading.Lock()                 # ctranslate2 is NOT concurrency-safe
rec = {"stream": None, "buf": None, "busy": False}
ui = {"state": "idle"}                          # idle | recording | transcribing
levels = collections.deque(maxlen=48)           # recent audio levels for the pill


def audio_cb(indata, n, t, status):
    buf = rec["buf"]
    if buf is not None:            # ignore stray callbacks when not recording
        buf.append(indata.copy())
        levels.append(min(1.0, float(np.sqrt(np.mean(np.square(indata)))) * 12.0))


def start_rec():
    with _lock:
        if rec["stream"] is not None or rec["busy"]:
            return
        rec["buf"] = []
        s = sd.InputStream(samplerate=cfg["sample_rate"], channels=1,
                           dtype="float32", blocksize=1600, callback=audio_cb)
        rec["stream"] = s
    levels.clear()
    ui["state"] = "recording"
    s.start()
    beep(cfg.get("start_sound", "Tink"))
    print("[native] RECORDING (press hotkey again to stop)", flush=True)


def stop_rec():
    with _lock:
        s = rec["stream"]
        if s is None:
            return
        rec["stream"] = None
        buf = rec["buf"]
        rec["buf"] = None          # callback stops appending immediately
        rec["busy"] = True
    try:
        s.stop(); s.close()
    except Exception:
        pass
    ui["state"] = "transcribing"
    beep(cfg.get("stop_sound", "Pop"))
    audio = (np.concatenate(buf).flatten() if buf
             else np.zeros(0, dtype="float32"))
    threading.Thread(target=transcribe, args=(audio,), daemon=True).start()


def transcribe(audio):
    try:
        dur = audio.size / cfg["sample_rate"]
        rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        print(f"[native] captured dur={dur:.2f}s rms={rms:.4f} peak={peak:.3f}",
              flush=True)
        # Silence gate (no VAD — it was eating real speech).
        if audio.size == 0 or dur < 0.4 or rms < 0.006:
            print("[native]  -> no speech, skipped", flush=True)
            return
        with _model_lock:          # serialize model access; iterate INSIDE lock
            segs, _ = model.transcribe(
                audio, language=cfg.get("language") or None,
                beam_size=5, condition_on_previous_text=False)
            text = " ".join(x.text.strip() for x in segs).strip()
        print(f"[native] transcript: {text!r}", flush=True)
        if text:
            out = cfg.get("output", "both")
            if out in ("clipboard", "both"):
                copy_clip(text)
            if out in ("type", "both"):
                type_text((" " + text) if cfg.get("insert_space") else text)
            beep(cfg.get("done_sound", "Glass"))
    except Exception as e:
        print(f"[native] transcribe error: {e}", flush=True)
    finally:
        with _lock:
            rec["busy"] = False
        ui["state"] = "idle"


def toggle():
    if rec["stream"] is not None:
        stop_rec()
    else:
        start_rec()


# ── global hotkey via Quartz event tap ───────────────────────────────────────
def tap_cb(proxy, etype, event, refcon):
    try:
        kc = int(CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode))
        mods = int(CGEventGetFlags(event)) & MOD_BITS
        if etype == KEYDOWN:
            if kc == HK_KC and (mods & HK_MODS) == HK_MODS and not st["down"]:
                st["down"] = True
                threading.Thread(target=toggle, daemon=True).start()
            elif (Q_KC is not None and kc == Q_KC
                  and (mods & Q_MODS) == Q_MODS and not st["qdown"]):
                st["qdown"] = True
                stop_event.set()
        elif etype == KEYUP:
            if kc == HK_KC:
                st["down"] = False
            if kc == Q_KC:
                st["qdown"] = False
    except Exception as e:
        print(f"[native] tap error: {e}", flush=True)
    return event


def run_tap():
    mask = (1 << KEYDOWN) | (1 << KEYUP) | (1 << FLAGS)
    tap = CGEventTapCreate(kCGSessionEventTap, kCGHeadInsertEventTap,
                           kCGEventTapOptionListenOnly, mask, tap_cb, None)
    if not tap:
        print("[native] EVENT TAP FAILED — grant Input Monitoring to this app.",
              flush=True)
        stop_event.set()
        return
    src = CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), src, kCFRunLoopCommonModes)
    CGEventTapEnable(tap, True)
    print(f"[native] listening: {cfg['hotkey']}  (quit {cfg['quit_hotkey']})",
          flush=True)
    CFRunLoopRun()


# ── animated waveform pill (optional, safe: pure Tk, no pynput/AppKit) ────────
class Pill:
    W, H = 300, 62
    PILL, REC, AMBER, BORDER = "#14161c", "#ff4b4b", "#ffb020", "#2a2f3a"

    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self.win.overrideredirect(True)         # borderless; doesn't take focus
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(self.win, width=self.W, height=self.H,
                                bg=self.PILL, highlightthickness=0)
        self.canvas.pack()
        self.visible = False
        self.phase = 0.0

    def _round(self, x1, y1, x2, y2, r, **kw):
        p = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2,
             x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.canvas.create_polygon(p, smooth=True, **kw)

    def show(self):
        if self.visible:
            return
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.win.geometry(f"{self.W}x{self.H}+{(sw-self.W)//2}+{sh-150}")
        self.win.deiconify()
        self.win.lift()
        try:
            self.win.attributes("-topmost", True, "-alpha", 0.96)
        except tk.TclError:
            pass
        self.visible = True

    def hide(self):
        if self.visible:
            self.win.withdraw()
            self.visible = False

    def draw(self, state, lv):
        import math
        c = self.canvas
        c.delete("all")
        W, H, cy = self.W, self.H, self.H / 2
        self._round(1, 1, W-1, H-1, 26, fill=self.PILL, outline=self.BORDER)
        listening = state == "recording"
        color = self.REC if listening else self.AMBER
        c.create_oval(20, cy-5, 30, cy+5, fill=color, outline="")
        x0, x1, n = 46, W-22, 22
        gap = (x1 - x0) / n
        if listening:
            lv = lv[-n:]
            lv = [0.0] * (n - len(lv)) + lv
        else:
            self.phase += 0.35
            lv = [(math.sin(self.phase + i*0.5) + 1) / 2 * 0.7 for i in range(n)]
        for i in range(n):
            bh = max(3, lv[i] * (H * 0.62))
            x = x0 + i*gap + gap/2
            c.create_line(x, cy-bh/2, x, cy+bh/2, fill=color, width=3,
                          capstyle="round")


def main():
    threading.Thread(target=run_tap, daemon=True).start()
    print("[native] ready — click a text field, press your hotkey, talk, "
          "press again.", flush=True)

    # No pill (or Tk unavailable) -> exactly the proven windowless behavior.
    if not cfg.get("overlay", True) or not _HAS_TK:
        try:
            stop_event.wait()
        except KeyboardInterrupt:
            pass
        print("[native] quitting.", flush=True)
        return

    root = tk.Tk()
    root.withdraw()
    pill = Pill(root)

    def poll():
        if stop_event.is_set():
            try:
                root.destroy()
            finally:
                return
        state = ui["state"]
        if state in ("recording", "transcribing"):
            pill.show()
            pill.draw(state, list(levels))
        else:
            pill.hide()
        root.after(45, poll)

    root.after(50, poll)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    print("[native] quitting.", flush=True)


main()
