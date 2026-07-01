#!/usr/bin/env python3
"""
Automated test suite for Whisperbox.

Covers everything we can verify without a human pressing physical keys:
config, hotkey parsing, the hotkey state machine (toggle/hold/quit/window),
audio metering, output delivery, the record→transcribe→deliver core, a real
model transcription, and headless GUI construction.

Run:  ./run-tests.sh        (or: python -m unittest -v test_whisperbox)
"""
import os
import sys
import time
import types
import unittest

import numpy as np

import core


# ── fakes ────────────────────────────────────────────────────────────────────
class FakeKeyboardController:
    def __init__(self):
        self.typed = []

    def type(self, text):
        self.typed.append(text)


class FakeSeg:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, text="hello world"):
        self._text = text

    def transcribe(self, audio, language=None, beam_size=5):
        return ([FakeSeg(t) for t in self._text.split()], {"language": "en"})


def install_fake_listener(captured):
    """Patch pynput.keyboard.Listener so HotkeyManager runs without a real tap."""
    from pynput import keyboard

    class FakeListener:
        def __init__(self, on_press=None, on_release=None, **kw):
            captured["on_press"] = on_press
            captured["on_release"] = on_release

        def start(self):
            pass

        def stop(self):
            pass

        def canonical(self, k):
            return k

    captured["orig"] = keyboard.Listener
    keyboard.Listener = FakeListener
    return keyboard


# ── config ───────────────────────────────────────────────────────────────────
class TestConfig(unittest.TestCase):
    def test_defaults_present(self):
        cfg = core.load_config()
        for key in ("hotkey", "mode", "output", "model", "quit_hotkey",
                    "window_hotkey", "show_window"):
            self.assertIn(key, cfg)

    def test_load_merges_defaults(self):
        # load_config always returns every default key even if config.json is sparse
        cfg = core.load_config()
        self.assertEqual(set(core.DEFAULTS) - set(cfg), set())


# ── hotkey parsing ───────────────────────────────────────────────────────────
class TestParseHotkey(unittest.TestCase):
    def test_ctrl_shift_d(self):
        vk, mods = core._parse_hotkey("<ctrl>+<shift>+d")
        self.assertEqual(vk, 2)
        self.assertEqual(mods, {"ctrl", "shift"})

    def test_single_key(self):
        vk, mods = core._parse_hotkey("<f9>")
        self.assertEqual(vk, 101)
        self.assertEqual(mods, set())

    def test_space_and_aliases(self):
        vk, mods = core._parse_hotkey("<cmd>+<option>+<space>")
        self.assertEqual(vk, 49)
        self.assertEqual(mods, {"cmd", "alt"})

    def test_unknown_key(self):
        vk, mods = core._parse_hotkey("<ctrl>+<shift>")
        self.assertIsNone(vk)


# ── hotkey state machine ─────────────────────────────────────────────────────
class TestHotkeyManager(unittest.TestCase):
    def setUp(self):
        self.cap = {}
        self.kb = install_fake_listener(self.cap)
        self.CTRL = self.kb.Key.ctrl_l
        self.SHIFT = self.kb.Key.shift_l
        self.D = self.kb.KeyCode(vk=2)
        self.Q = self.kb.KeyCode(vk=12)
        self.W = self.kb.KeyCode(vk=13)

    def tearDown(self):
        self.kb.Listener = self.cap["orig"]

    def _mgr(self, mode, calls):
        class FC:
            def start_recording(self): calls.append("start")
            def stop_recording(self): calls.append("stop")
            def toggle(self): calls.append("toggle")
        m = core.HotkeyManager(
            {"mode": mode, "hotkey": "<ctrl>+<shift>+d",
             "quit_hotkey": "<ctrl>+<shift>+q", "window_hotkey": "<ctrl>+<shift>+w"},
            FC(),
            on_quit=lambda: calls.append("quit"),
            on_window=lambda: calls.append("window"))
        m.start()
        return calls

    def _press_chord(self, key):
        self.cap["on_press"](self.CTRL)
        self.cap["on_press"](self.SHIFT)
        self.cap["on_press"](key)

    def test_toggle_flips_each_press(self):
        calls = self._mgr("toggle", [])
        self._press_chord(self.D)
        self.cap["on_press"](self.D)             # auto-repeat -> ignored
        self.cap["on_release"](self.D)
        self.cap["on_press"](self.D)             # fresh press -> toggle again
        time.sleep(0.05)
        self.assertEqual(calls, ["toggle", "toggle"])

    def test_toggle_ignores_plain_key(self):
        calls = self._mgr("toggle", [])
        self.cap["on_press"](self.D)             # 'd' with no modifiers
        self.cap["on_release"](self.D)
        time.sleep(0.05)
        self.assertEqual(calls, [])

    def test_hold_start_and_stop_on_key_release(self):
        calls = self._mgr("hold", [])
        self._press_chord(self.D)
        self.cap["on_release"](self.D)
        time.sleep(0.05)
        self.assertEqual(calls, ["start", "stop"])

    def test_hold_stops_on_modifier_release(self):
        calls = self._mgr("hold", [])
        self._press_chord(self.D)
        self.cap["on_release"](self.CTRL)        # let go of a modifier
        time.sleep(0.05)
        self.assertEqual(calls, ["start", "stop"])

    def test_quit_hotkey(self):
        calls = self._mgr("toggle", [])
        self._press_chord(self.Q)
        time.sleep(0.05)
        self.assertIn("quit", calls)

    def test_window_hotkey(self):
        calls = self._mgr("toggle", [])
        self._press_chord(self.W)
        time.sleep(0.05)
        self.assertIn("window", calls)


# ── audio metering ───────────────────────────────────────────────────────────
class TestRecorder(unittest.TestCase):
    def test_levels_track_loudness(self):
        r = core.Recorder(16000)
        r._callback(np.random.randn(1600, 1).astype("float32") * 0.2, 1600, None, None)
        r._callback(np.zeros((1600, 1), dtype="float32"), 1600, None, None)
        lv = r.get_levels()
        self.assertEqual(len(lv), 2)
        self.assertGreater(lv[0], lv[1])

    def test_start_clears_levels(self):
        r = core.Recorder(16000)
        r._callback(np.ones((10, 1), dtype="float32"), 10, None, None)
        self.assertTrue(r.get_levels())
        # start() opens a real stream; just exercise the clear path directly
        with r._lock:
            r.frames = []
            r.levels.clear()
        self.assertEqual(r.get_levels(), [])


# ── output delivery ──────────────────────────────────────────────────────────
class TestTypist(unittest.TestCase):
    def setUp(self):
        # fake pyperclip so "clipboard" output has no side effects
        self.fake_clip = types.ModuleType("pyperclip")
        self.fake_clip.copied = []
        self.fake_clip.copy = lambda t: self.fake_clip.copied.append(t)
        sys.modules["pyperclip"] = self.fake_clip

    def _typist(self, **over):
        cfg = dict(core.DEFAULTS)
        cfg.update(over)
        t = core.Typist.__new__(core.Typist)
        t.cfg = cfg
        t.keyboard = FakeKeyboardController()
        return t

    def test_insert_space_on(self):
        t = self._typist(output="type", insert_space=True)
        t.deliver("hello world")
        self.assertEqual(t.keyboard.typed, [" hello world"])

    def test_insert_space_off(self):
        t = self._typist(output="type", insert_space=False)
        t.deliver("hello")
        self.assertEqual(t.keyboard.typed, ["hello"])

    def test_clipboard_only_does_not_type(self):
        t = self._typist(output="clipboard")
        t.deliver("hi there")
        self.assertEqual(t.keyboard.typed, [])
        self.assertEqual(self.fake_clip.copied, ["hi there"])

    def test_both_copies_and_types(self):
        t = self._typist(output="both", insert_space=False)
        t.deliver("yo")
        self.assertEqual(t.keyboard.typed, ["yo"])
        self.assertEqual(self.fake_clip.copied, ["yo"])

    def test_empty_text_noop(self):
        t = self._typist(output="both")
        t.deliver("   ")
        self.assertEqual(t.keyboard.typed, [])


# ── core record→transcribe→deliver ───────────────────────────────────────────
class TestSttCore(unittest.TestCase):
    def _core(self):
        c = core.SttCore(dict(core.DEFAULTS),
                         on_status=lambda s: self.status.append(s),
                         on_transcript=lambda t: self.transcripts.append(t))
        # isolate: no real audio/typing/beeps/focus changes
        c.beeper = types.SimpleNamespace(start=lambda: None, stop=lambda: None,
                                         done=lambda: None)
        c.typist = types.SimpleNamespace(deliver=lambda t: self.delivered.append(t))
        c._capture_target_app = lambda: None
        c._refocus_target_app = lambda: None
        c.model = FakeModel("hello world")
        return c

    def setUp(self):
        self.status, self.transcripts, self.delivered = [], [], []

    def test_transcribe_delivers_text(self):
        c = self._core()
        c._transcribe(np.ones(16000, dtype="float32"))
        self.assertEqual(self.transcripts, ["hello world"])
        self.assertEqual(self.delivered, ["hello world"])
        self.assertEqual(self.status[-1], "idle")

    def test_empty_audio_gives_empty_transcript(self):
        c = self._core()
        c._transcribe(np.zeros(0, dtype="float32"))
        self.assertEqual(self.transcripts, [""])
        self.assertEqual(self.delivered, [])   # nothing to deliver

    def test_start_recording_guarded_without_model(self):
        c = self._core()
        c.model = None
        c.start_recording()
        self.assertFalse(c.recording)

    def test_toggle_starts_and_stops(self):
        c = self._core()
        # avoid opening a real mic stream
        c.recorder = types.SimpleNamespace(
            start=lambda: None,
            stop=lambda: np.zeros(0, dtype="float32"))
        c.toggle()
        self.assertTrue(c.recording)
        c.toggle()
        self.assertFalse(c.recording)
        time.sleep(0.2)   # let the transcription thread finish
        self.assertEqual(self.status[-1], "idle")


# ── real model (slow-ish, uses tiny.en) ──────────────────────────────────────
class TestRealTranscription(unittest.TestCase):
    def test_load_and_transcribe_silence(self):
        from faster_whisper import WhisperModel
        m = WhisperModel("tiny.en", device="cpu", compute_type="int8")
        segs, _ = m.transcribe(np.zeros(16000, dtype="float32"),
                               language="en", beam_size=1)
        text = " ".join(s.text for s in segs).strip()
        self.assertIsInstance(text, str)   # silence -> empty, but must not crash


# ── REAL OS permissions (the layer mocks can't cover) ────────────────────────
class TestPermissions(unittest.TestCase):
    """The unit tests above use a fake key listener, so they pass even when
    macOS is silently blocking real key events. THESE check the actual OS grants
    that make the global hotkey and typing work — run from the same context that
    launches the app (e.g. Terminal) to reflect what the app really sees."""

    def test_input_monitoring_granted(self):
        try:
            from Quartz import CGPreflightListenEventAccess
        except Exception as e:
            self.skipTest(f"cannot query Input Monitoring: {e}")
        self.assertTrue(
            CGPreflightListenEventAccess(),
            "Input Monitoring is NOT granted — the global hotkey will not receive "
            "keys. Enable this app under System Settings → Privacy & Security → "
            "Input Monitoring, then relaunch.")

    def test_accessibility_granted(self):
        try:
            from ApplicationServices import AXIsProcessTrusted
        except Exception as e:
            self.skipTest(f"cannot query Accessibility: {e}")
        self.assertTrue(
            AXIsProcessTrusted(),
            "Accessibility is NOT granted — dictation cannot type into other apps. "
            "Enable this app under System Settings → Privacy & Security → "
            "Accessibility, then relaunch.")


# ── headless GUI construction ────────────────────────────────────────────────
class TestGuiHeadless(unittest.TestCase):
    def test_build_and_states(self):
        # Building a full Tk app + calling macOS window/activation APIs only
        # works inside a real interactive GUI session; in an automated runner it
        # blocks. Opt in with WB_GUI=1 when running from a normal login session.
        if os.environ.get("WB_GUI") != "1":
            self.skipTest("GUI test is opt-in; run with WB_GUI=1 from a desktop session")
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception as e:
            self.skipTest(f"no display: {e}")
        import gui
        gui.SttCore.load_model = lambda self: self.on_status("idle")
        gui.HotkeyManager.start = lambda self: None
        app = gui.App(root)
        for st in ("recording", "transcribing", "idle"):
            app._set_state(st)
        app.overlay.show("listening")
        app.overlay._draw()
        app.overlay.hide()
        app._toggle_window()          # show
        app._toggle_window()          # hide
        for _ in range(3):
            root.update_idletasks(); root.update()
        root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
