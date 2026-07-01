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

    def start_recording(self):
        if self.recording or self._busy or self.model is None:
            return
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
            self.typist.deliver(text)
            self.beeper.done()
        except Exception as e:
            self.on_error(f"Transcription error: {e}")
        finally:
            self._busy = False
            self.on_status("idle")


class HotkeyManager:
    """Registers the programmable global hotkey and drives an SttCore."""

    def __init__(self, cfg, core, on_quit=None):
        self.cfg = cfg
        self.core = core
        self.on_quit = on_quit or (lambda: None)
        self._listener = None
        self._held = False

    def start(self):
        from pynput import keyboard
        mode = self.cfg["mode"]
        hotkey = self.cfg["hotkey"]
        quit_hotkey = self.cfg["quit_hotkey"]

        if mode == "hold":
            self._start_hold(keyboard, hotkey, quit_hotkey)
        else:
            self._listener = keyboard.GlobalHotKeys({
                hotkey: self.core.toggle,
                quit_hotkey: self.on_quit,
            })
            self._listener.start()

    def _start_hold(self, keyboard, hotkey, quit_hotkey):
        hk = keyboard.HotKey(keyboard.HotKey.parse(hotkey), lambda: None)
        qk = keyboard.HotKey(keyboard.HotKey.parse(quit_hotkey), self.on_quit)

        def active(h):
            return len(h._state) == len(h._keys)

        def on_press(key):
            c = self._listener.canonical(key)
            hk.press(c)
            qk.press(c)
            if active(hk) and not self._held:
                self._held = True
                self.core.start_recording()

        def on_release(key):
            c = self._listener.canonical(key)
            hk.release(c)
            qk.release(c)
            if self._held and not active(hk):
                self._held = False
                self.core.stop_recording()

        self._listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._listener.start()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
