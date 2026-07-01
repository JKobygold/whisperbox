#!/usr/bin/env python3
"""
Reusable, offline speech-to-text engine.

`SttCore` owns the microphone, the Whisper model and the output delivery, and
reports what it's doing through two callbacks so any front-end (CLI or GUI) can
drive it:

    on_status(state)      state in {"loading", "idle", "recording",
                                    "transcribing"}
    on_transcript(text)   the recognized text, before it is delivered

`HotkeyManager` registers a global, programmable hotkey (toggle or hold mode)
and calls back into the core.
"""

import collections
import json
import math
import os
import sys
import threading
import time

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULTS = {
    "hotkey": "<ctrl>+<alt>+<space>",
    "mode": "toggle",            # "toggle" (press to start, press to stop) or "hold" (push-to-talk)
    "output": "both",           # "clipboard", "type", or "both"
    "auto_paste": False,         # after copying, simulate Cmd+V to paste into the focused app
    "model": "small.en",        # tiny(.en) / base(.en) / small(.en) / medium(.en) / large-v3
    "language": "en",           # None/"" for auto-detect
    "compute_type": "int8",     # int8 is fast + light on RAM; use "int8_float16" or "float16" for more accuracy
    "device": "cpu",            # "cpu" (works everywhere) or "cuda"
    "beam_size": 5,
    "sample_rate": 16000,
    "sound_feedback": True,
    "quit_hotkey": "<ctrl>+<alt>+q",
    "overlay": True,             # show the floating "listening" pill while dictating
    "insert_space": True,        # add a leading space so dictation appends cleanly at the cursor
}


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                user = json.load(f)
            cfg.update({k: v for k, v in user.items() if v is not None})
        except Exception as e:
            print(f"[config] Could not parse config.json ({e}); using defaults.")
    else:
        print("[config] No config.json found; using defaults.")
    return cfg


def save_config(cfg):
    """Persist the given settings dict to config.json (only known keys)."""
    out = {k: cfg[k] for k in DEFAULTS if k in cfg}
    with open(CONFIG_PATH, "w") as f:
        json.dump(out, f, indent=2)


class Beeper:
    """Tiny audio cues so you know when recording starts/stops (macOS 'afplay')."""

    def __init__(self, enabled):
        self.enabled = enabled and sys.platform == "darwin"

    def _play(self, name):
        if not self.enabled:
            return
        path = f"/System/Library/Sounds/{name}.aiff"
        os.system(f"afplay '{path}' >/dev/null 2>&1 &")

    def start(self):
        self._play("Tink")

    def stop(self):
        self._play("Pop")

    def done(self):
        self._play("Glass")


class Recorder:
    """Captures microphone audio into memory while active."""

    def __init__(self, sample_rate):
        import sounddevice as sd
        import numpy as np
        self.sd = sd
        self.np = np
        self.sample_rate = sample_rate
        self.stream = None
        self.frames = []
        self.levels = collections.deque(maxlen=48)  # recent audio levels for the waveform
        self._lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}", file=sys.stderr)
        # RMS loudness of this block, scaled to a roughly 0..1 range for display
        rms = float(self.np.sqrt(self.np.mean(self.np.square(indata))))
        level = min(1.0, rms * 12.0)
        with self._lock:
            self.frames.append(indata.copy())
            self.levels.append(level)

    def get_levels(self):
        with self._lock:
            return list(self.levels)

    def start(self):
        with self._lock:
            self.frames = []
            self.levels.clear()
        self.stream = self.sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self.stream.start()

    def stop(self):
        import numpy as np
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        with self._lock:
            frames = self.frames
            self.frames = []
        if not frames:
            return np.zeros(0, dtype="float32")
        return np.concatenate(frames, axis=0).flatten()


class Typist:
    """Delivers transcribed text: clipboard, typing at the cursor, or both."""

    def __init__(self, cfg):
        self.cfg = cfg
        from pynput.keyboard import Controller
        self.keyboard = Controller()

    def deliver(self, text):
        text = text.strip()
        if not text:
            return
        mode = self.cfg["output"]
        if mode in ("clipboard", "both"):
            try:
                import pyperclip
                pyperclip.copy(text)
            except Exception as e:
                print(f"[output] clipboard failed: {e}")

        if mode in ("type", "both"):
            # Insert at the caret, appending cleanly to whatever is already there.
            typed = (" " + text) if self.cfg.get("insert_space") else text
            try:
                self.keyboard.type(typed)
            except Exception as e:
                print(f"[output] typing failed (grant Accessibility permission?): {e}")

        if self.cfg["auto_paste"] and mode in ("clipboard", "both"):
            self._paste()

    def _paste(self):
        try:
            from pynput.keyboard import Key
            with self.keyboard.pressed(Key.cmd):
                self.keyboard.press("v")
                self.keyboard.release("v")
        except Exception as e:
            print(f"[output] auto-paste failed: {e}")


class SttCore:
    """Microphone + Whisper + output, wired to status/transcript callbacks."""

    def __init__(self, cfg, on_status=None, on_transcript=None, on_error=None):
        self.cfg = cfg
        self.on_status = on_status or (lambda s: None)
        self.on_transcript = on_transcript or (lambda t: None)
        self.on_error = on_error or (lambda e: None)
        self.beeper = Beeper(cfg["sound_feedback"])
        self.recorder = Recorder(cfg["sample_rate"])
        self.typist = Typist(cfg)
        self.recording = False
        self._busy = False
        self.model = None
        self._target_app = None   # the app/field to type back into

    def load_model(self):
        from faster_whisper import WhisperModel
        self.on_status("loading")
        print(f"[model] Loading '{self.cfg['model']}' ({self.cfg['compute_type']} on "
              f"{self.cfg['device']})... first run downloads it, then it's cached & offline.")
        t0 = time.time()
        self.model = WhisperModel(
            self.cfg["model"],
            device=self.cfg["device"],
            compute_type=self.cfg["compute_type"],
        )
        print(f"[model] Ready in {time.time() - t0:.1f}s.")
        self.on_status("idle")

    def _capture_target_app(self):
        """Remember which app is frontmost right now — that's the text field the
        user is 'latched' onto. We restore focus to it before typing."""
        try:
            from AppKit import NSWorkspace
            self._target_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        except Exception:
            self._target_app = None

    def _refocus_target_app(self):
        """Re-latch onto the remembered app so the caret is back in the user's
        field, then keystrokes land there instead of in our own window."""
        try:
            if self._target_app is not None:
                # NSApplicationActivateIgnoringOtherApps = 1 << 1
                self._target_app.activateWithOptions_(1 << 1)
                time.sleep(0.12)   # give macOS a moment to restore field focus
        except Exception:
            pass

    def start_recording(self):
        if self.recording or self._busy or self.model is None:
            return
        # capture the target BEFORE our pill/window can steal focus
        self._capture_target_app()
        self.recording = True
        self.on_status("recording")
        self.beeper.start()
        try:
            self.recorder.start()
        except Exception as e:
            self.recording = False
            self.on_error(f"Microphone error: {e}")
            self.on_status("idle")

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        self.beeper.stop()
        audio = self.recorder.stop()
        self.on_status("transcribing")
        self._busy = True
        threading.Thread(target=self._transcribe, args=(audio,), daemon=True).start()

    def toggle(self):
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def _transcribe(self, audio):
        try:
            if audio.size == 0:
                self.on_transcript("")
                return
            lang = self.cfg["language"] or None
            segments, _ = self.model.transcribe(
                audio,
                language=lang,
                beam_size=self.cfg["beam_size"],
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            self.on_transcript(text)
            if text:
                self._refocus_target_app()   # re-latch onto the user's field
            self.typist.deliver(text)
            self.beeper.done()
        except Exception as e:
            self.on_error(f"Transcription error: {e}")
        finally:
            self._busy = False
            self.on_status("idle")


# ── macOS raw-keycode hotkey support ─────────────────────────────────────────
# hotkey modifier names -> canonical category
_MODNAMES = {
    "shift": "shift",
    "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt", "option": "alt", "opt": "alt",
    "cmd": "cmd", "command": "cmd", "super": "cmd", "win": "cmd",
}
# US-layout virtual key codes for non-modifier keys
_KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8,
    "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
    "o": 31, "u": 32, "i": 34, "p": 35, "l": 37, "j": 38, "k": 40, "n": 45,
    "m": 46,
    "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26, "8": 28,
    "9": 25, "0": 29,
    "space": 49, "return": 36, "enter": 36, "tab": 48, "escape": 53, "esc": 53,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98,
    "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}
def _parse_hotkey(spec):
    """'<ctrl>+<shift>+d' -> (main_vk or None, {'ctrl', 'shift'})."""
    mods, main_vk = set(), None
    for tok in spec.split("+"):
        t = tok.strip().strip("<>").lower()
        if t in _MODNAMES:
            mods.add(_MODNAMES[t])
        elif t in _KEYCODES:
            main_vk = _KEYCODES[t]
    return main_vk, mods


class HotkeyManager:
    """Registers the programmable global hotkey and drives an SttCore."""

    def __init__(self, cfg, core, on_quit=None):
        self.cfg = cfg
        self.core = core
        self.on_quit = on_quit or (lambda: None)
        self._listener = None
        self._held = False

    def start(self):
        """Listen for the hotkey with a plain global key listener.

        This is the approach proven to work reliably on macOS (see the staged
        hotkey tests): track modifier keys by press/release, and match the main
        key by its hardware code (vk) so Shift changing 'd'->'D', or Option
        remapping characters, never breaks detection. We deliberately avoid
        pynput.GlobalHotKeys / HotKey.parse and event-tap suppression, both of
        which failed in practice here."""
        from pynput import keyboard
        K = keyboard.Key

        modsets = {
            "ctrl": {K.ctrl, K.ctrl_l, K.ctrl_r},
            "shift": {K.shift, K.shift_l, K.shift_r},
            "alt": {K.alt, K.alt_l, K.alt_r, getattr(K, "alt_gr", K.alt)},
            "cmd": {K.cmd, K.cmd_l, K.cmd_r},
        }
        key_to_cat = {kk: cat for cat, keys in modsets.items() for kk in keys}

        mode = self.cfg["mode"]
        main_vk, main_mods = _parse_hotkey(self.cfg["hotkey"])
        quit_vk, quit_mods = _parse_hotkey(self.cfg["quit_hotkey"])

        held = set()                      # modifier categories currently down
        st = {"main_down": False, "hold_rec": False, "quit_down": False}

        def fire(target):
            # run off the listener thread so recording/model work never stalls input
            threading.Thread(target=target, daemon=True).start()

        def on_press(k):
            cat = key_to_cat.get(k)
            if cat:
                held.add(cat)
                return
            vk = getattr(k, "vk", None)
            if (vk == main_vk and main_mods <= held and not st["main_down"]):
                st["main_down"] = True
                if mode == "hold":
                    st["hold_rec"] = True
                    fire(self.core.start_recording)
                else:
                    fire(self.core.toggle)
            if (quit_vk is not None and vk == quit_vk and quit_mods <= held
                    and not st["quit_down"]):
                st["quit_down"] = True
                fire(self.on_quit)

        def on_release(k):
            cat = key_to_cat.get(k)
            if cat:
                held.discard(cat)
                if mode == "hold" and st["hold_rec"] and cat in main_mods:
                    st["hold_rec"] = False
                    st["main_down"] = False
                    fire(self.core.stop_recording)
                return
            vk = getattr(k, "vk", None)
            if vk == main_vk:
                st["main_down"] = False
                if mode == "hold" and st["hold_rec"]:
                    st["hold_rec"] = False
                    fire(self.core.stop_recording)
            if quit_vk is not None and vk == quit_vk:
                st["quit_down"] = False

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.start()
        print(f"[hotkey] listening: {self.cfg['hotkey']} ({mode} mode), "
              f"quit {self.cfg['quit_hotkey']}")

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
