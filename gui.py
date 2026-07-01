#!/usr/bin/env python3
"""
Graphical front-end for the local speech-to-text engine.

A small dark window with a big microphone button you can click, a live status
indicator, the latest transcript, and inline settings. The programmable global
hotkey still works while the window is in the background.

Run with:  python gui.py   (or ./run.sh)
"""

import math
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk

from core import DEFAULTS, HotkeyManager, SttCore, load_config, save_config

# ── palette ────────────────────────────────────────────────────────────────
BG      = "#0f1115"
CARD    = "#171a21"
CARD2   = "#1e222b"
ACCENT  = "#4c8bf5"
REC     = "#ff4b4b"
AMBER   = "#ffb020"
GREEN   = "#38c172"
TEXT    = "#e6e8ec"
MUTED   = "#8b90a0"
BORDER  = "#2a2f3a"

MODELS  = ["tiny.en", "base.en", "small.en", "medium.en",
           "tiny", "base", "small", "medium", "large-v3"]

STATE_COLOR = {
    "loading":      MUTED,
    "idle":         ACCENT,
    "recording":    REC,
    "transcribing": AMBER,
}
STATE_TEXT = {
    "loading":      "Loading model…",
    "idle":         "Ready — click the mic or press your hotkey",
    "recording":    "Recording… click again to stop",
    "transcribing": "Transcribing…",
}


PILL = "#14161c"


class Overlay:
    """A small floating pill that appears near the bottom of the screen while
    you dictate — a live waveform + status, in the spirit of Wispr / macOS
    dictation. It never takes keyboard focus, so your text field stays active
    and the transcription types straight into it."""

    W, H = 300, 62

    def __init__(self, root, core):
        self.core = core
        self.mode = "listening"
        self.phase = 0.0
        self.visible = False

        self.win = tk.Toplevel(root)
        self.win.withdraw()
        self._make_nonactivating()
        try:
            self.win.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(self.win, width=self.W, height=self.H,
                                bg=PILL, highlightthickness=0)
        self.canvas.pack()
        self._animate()

    def _make_nonactivating(self):
        """Borderless floating pill. (Focus is handled by the core's re-latch,
        which restores your text field before typing — so we avoid the fragile
        native window-style calls that were crashing Python at launch.)"""
        self.win.overrideredirect(True)

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1+r, y1, x2-r, y1, x2, y1, x2, y1+r, x2, y2-r, x2, y2,
               x2-r, y2, x1+r, y2, x1, y2, x1, y2-r, x1, y1+r, x1, y1]
        return self.canvas.create_polygon(pts, smooth=True, **kw)

    def show(self, mode):
        self.mode = mode
        if not self.visible:
            sw = self.win.winfo_screenwidth()
            sh = self.win.winfo_screenheight()
            x = (sw - self.W) // 2
            y = sh - 150
            self.win.geometry(f"{self.W}x{self.H}+{x}+{y}")
            self.win.deiconify()
            self.win.lift()
            try:
                self.win.attributes("-topmost", True, "-alpha", 0.96)
            except tk.TclError:
                pass
            self.visible = True

    def set_mode(self, mode):
        self.mode = mode

    def hide(self):
        if self.visible:
            self.win.withdraw()
            self.visible = False

    def _animate(self):
        if self.visible:
            self._draw()
        self.win.after(45, self._animate)

    def _draw(self):
        c = self.canvas
        c.delete("all")
        W, H = self.W, self.H
        self._round_rect(1, 1, W-1, H-1, 26, fill=PILL, outline=BORDER)

        listening = self.mode == "listening"
        color = REC if listening else AMBER
        cy = H / 2

        # state dot on the left
        c.create_oval(20, cy-5, 30, cy+5, fill=color, outline="")

        # waveform bars
        x0, x1 = 46, W - 22
        n = 22
        gap = (x1 - x0) / n
        if listening:
            lv = self.core.recorder.get_levels()
            lv = lv[-n:]
            lv = [0.0] * (n - len(lv)) + lv    # right-align newest samples
        else:
            self.phase += 0.35
            lv = [(math.sin(self.phase + i * 0.5) + 1) / 2 * 0.7 for i in range(n)]

        for i in range(n):
            cx = x0 + i * gap + gap / 2
            bh = max(3, lv[i] * (H * 0.62))
            c.create_line(cx, cy - bh/2, cx, cy + bh/2,
                          fill=color, width=3, capstyle="round")


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.events = queue.Queue()
        self.state = "loading"
        self.model_sig = self._model_sig()
        self.hotkeys = None

        self.core = SttCore(
            self.cfg,
            on_status=lambda s: self.events.put(("status", s)),
            on_transcript=lambda t: self.events.put(("transcript", t)),
            on_error=lambda e: self.events.put(("error", e)),
            # deliver (type into the field) MUST happen on the main thread on
            # macOS, or the input-source APIs crash. Route it through the pump.
            on_deliver=lambda t: self.events.put(("deliver", t)),
        )

        self._build_ui()
        self.overlay = Overlay(self.root, self.core)
        self.root.after(60, self._pump)
        self._pulse_phase = 0.0
        self._animate()

        # Optionally start hidden. Focus is handled by the re-latch logic in the
        # core (it restores your field before typing), so a visible window is
        # fine and stable.
        if not self.cfg.get("show_window", True):
            self.root.withdraw()

        # Load the model in the background so the window appears instantly.
        threading.Thread(target=self._boot, daemon=True).start()

    # ── setup ───────────────────────────────────────────────────────────────
    def _model_sig(self):
        return (self.cfg["model"], self.cfg["compute_type"], self.cfg["device"])

    def _boot(self):
        try:
            self.core.load_model()
        except Exception as e:
            self.events.put(("error", f"Model load failed: {e}"))
            return
        self.hotkeys = HotkeyManager(
            self.cfg, self.core,
            on_quit=lambda: self.events.put(("quit", None)),
            on_window=lambda: self.events.put(("window", None)),
        )
        try:
            self.hotkeys.start()
        except Exception as e:
            self.events.put(("error", f"Hotkey error (grant Accessibility/Input Monitoring): {e}"))

    # ── UI construction ──────────────────────────────────────────────────────
    def _build_ui(self):
        r = self.root
        r.title("Local Speech-to-Text")
        r.configure(bg=BG)
        r.geometry("440x640")
        r.minsize(440, 640)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TCombobox", fieldbackground=CARD2, background=CARD2,
                        foreground=TEXT, arrowcolor=TEXT, bordercolor=BORDER)
        style.map("TCombobox", fieldbackground=[("readonly", CARD2)],
                  foreground=[("readonly", TEXT)])

        # header
        tk.Label(r, text="Speech-to-Text", bg=BG, fg=TEXT,
                 font=("Helvetica", 20, "bold")).pack(pady=(20, 0))
        tk.Label(r, text="fully offline · on-device", bg=BG, fg=MUTED,
                 font=("Helvetica", 11)).pack(pady=(2, 10))

        # big mic button
        self.canvas = tk.Canvas(r, width=200, height=200, bg=BG,
                                highlightthickness=0)
        self.canvas.pack(pady=(6, 4))
        self.canvas.bind("<Button-1>", lambda e: self._on_mic_click())

        # status line
        self.status_lbl = tk.Label(r, text=STATE_TEXT["loading"], bg=BG, fg=MUTED,
                                   font=("Helvetica", 12))
        self.status_lbl.pack(pady=(0, 10))

        # transcript card
        card = tk.Frame(r, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        card.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        head = tk.Frame(card, bg=CARD)
        head.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(head, text="Last transcript", bg=CARD, fg=MUTED,
                 font=("Helvetica", 10, "bold")).pack(side="left")
        self.copy_btn = tk.Button(head, text="Copy", command=self._copy,
                                  bg=CARD2, fg=TEXT, activebackground=ACCENT,
                                  activeforeground="white", relief="flat",
                                  font=("Helvetica", 10), padx=10, cursor="hand2",
                                  bd=0, highlightthickness=0)
        self.copy_btn.pack(side="right")
        self.transcript = tk.Text(card, height=5, wrap="word", bg=CARD, fg=TEXT,
                                  insertbackground=TEXT, relief="flat",
                                  font=("Helvetica", 12), padx=12, pady=6,
                                  highlightthickness=0)
        self.transcript.pack(fill="both", expand=True, padx=4, pady=(0, 10))

        # settings (collapsible)
        self.settings_open = tk.BooleanVar(value=False)
        self.toggle_btn = tk.Button(r, text="⚙  Settings", command=self._toggle_settings,
                                    bg=BG, fg=MUTED, activebackground=BG,
                                    activeforeground=TEXT, relief="flat",
                                    font=("Helvetica", 11), cursor="hand2",
                                    bd=0, highlightthickness=0)
        self.toggle_btn.pack(pady=(0, 2))
        self.settings = tk.Frame(r, bg=BG)
        self._build_settings(self.settings)

        r.protocol("WM_DELETE_WINDOW", self._quit)
        self._draw_mic()

    def _build_settings(self, parent):
        self.vars = {}

        def row(label, widget):
            fr = tk.Frame(parent, bg=BG)
            fr.pack(fill="x", padx=18, pady=4)
            tk.Label(fr, text=label, bg=BG, fg=MUTED, width=12, anchor="w",
                     font=("Helvetica", 11)).pack(side="left")
            widget.pack(side="right", fill="x", expand=True)
            return fr

        self.vars["hotkey"] = tk.StringVar(value=self.cfg["hotkey"])
        e = tk.Entry(parent, textvariable=self.vars["hotkey"], bg=CARD2, fg=TEXT,
                     insertbackground=TEXT, relief="flat", font=("Helvetica", 11))
        row("Hotkey", e)

        self.vars["mode"] = tk.StringVar(value=self.cfg["mode"])
        row("Mode", ttk.Combobox(parent, textvariable=self.vars["mode"],
                                 values=["toggle", "hold"], state="readonly"))

        self.vars["output"] = tk.StringVar(value=self.cfg["output"])
        row("Output", ttk.Combobox(parent, textvariable=self.vars["output"],
                                   values=["both", "clipboard", "type"], state="readonly"))

        self.vars["model"] = tk.StringVar(value=self.cfg["model"])
        row("Model", ttk.Combobox(parent, textvariable=self.vars["model"],
                                  values=MODELS, state="readonly"))

        def check(key, label):
            var = tk.BooleanVar(value=bool(self.cfg.get(key)))
            self.vars[key] = var
            cb = tk.Checkbutton(parent, text=label, variable=var, bg=BG, fg=TEXT,
                                selectcolor=CARD2, activebackground=BG,
                                activeforeground=TEXT, anchor="w",
                                font=("Helvetica", 11), highlightthickness=0, bd=0)
            cb.pack(fill="x", padx=16, pady=1)

        check("overlay", "  Show floating pill while dictating")
        check("insert_space", "  Add a space before inserted text (clean append)")

        tk.Label(parent, text="Hotkey format: <ctrl>+<alt>+<space>, <cmd>+<shift>+d, <f9>",
                 bg=BG, fg=MUTED, font=("Helvetica", 9), wraplength=380,
                 justify="left").pack(fill="x", padx=18, pady=(4, 2))

        self.save_btn = tk.Button(parent, text="Save settings", command=self._save,
                                  bg=ACCENT, fg="white", activebackground="#3a72d0",
                                  activeforeground="white", relief="flat",
                                  font=("Helvetica", 11, "bold"), pady=6,
                                  cursor="hand2", bd=0, highlightthickness=0)
        self.save_btn.pack(fill="x", padx=18, pady=(6, 4))
        self.save_hint = tk.Label(parent, text="", bg=BG, fg=GREEN,
                                  font=("Helvetica", 10))
        self.save_hint.pack()

    def _toggle_settings(self):
        if self.settings_open.get():
            self.settings.pack_forget()
            self.settings_open.set(False)
        else:
            self.settings.pack(fill="x", pady=(0, 10))
            self.settings_open.set(True)

    # ── drawing ──────────────────────────────────────────────────────────────
    def _draw_mic(self, pulse=0.0):
        c = self.canvas
        c.delete("all")
        cx, cy = 100, 100
        color = STATE_COLOR.get(self.state, ACCENT)

        # pulsing halo while recording
        if self.state == "recording":
            r_halo = 74 + pulse * 12
            c.create_oval(cx - r_halo, cy - r_halo, cx + r_halo, cy + r_halo,
                          outline=REC, width=2)
        base_r = 66
        c.create_oval(cx - base_r, cy - base_r, cx + base_r, cy + base_r,
                      fill=color, outline="")

        # mic glyph (white)
        w = "white"
        c.create_oval(cx - 12, cy - 30, cx + 12, cy + 6, fill=w, outline="")
        c.create_arc(cx - 20, cy - 6, cx + 20, cy + 24, start=180, extent=180,
                     style="arc", outline=w, width=3)
        c.create_line(cx, cy + 24, cx, cy + 34, fill=w, width=3)
        c.create_line(cx - 12, cy + 34, cx + 12, cy + 34, fill=w, width=3)

    def _animate(self):
        import math
        if self.state == "recording":
            self._pulse_phase += 0.18
            self._draw_mic(pulse=(math.sin(self._pulse_phase) + 1) / 2)
        self.root.after(40, self._animate)

    # ── actions ──────────────────────────────────────────────────────────────
    def _on_mic_click(self):
        if self.state in ("idle", "recording"):
            self.core.toggle()

    def _set_state(self, state):
        self.state = state
        self.status_lbl.config(text=STATE_TEXT.get(state, state),
                               fg=STATE_COLOR.get(state, MUTED))
        self._draw_mic()

        # drive the floating pill
        if self.cfg.get("overlay"):
            if state == "recording":
                self.overlay.show("listening")
            elif state == "transcribing":
                self.overlay.set_mode("transcribing")
            else:
                self.overlay.hide()
        else:
            self.overlay.hide()

    def _show_transcript(self, text):
        self.transcript.delete("1.0", "end")
        self.transcript.insert("1.0", text if text else "(nothing transcribed)")

    def _copy(self):
        text = self.transcript.get("1.0", "end").strip()
        if text and text != "(nothing transcribed)":
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.copy_btn.config(text="Copied ✓")
            self.root.after(1200, lambda: self.copy_btn.config(text="Copy"))

    def _save(self):
        new = {
            "hotkey": self.vars["hotkey"].get().strip() or DEFAULTS["hotkey"],
            "mode": self.vars["mode"].get(),
            "output": self.vars["output"].get(),
            "overlay": bool(self.vars["overlay"].get()),
            "insert_space": bool(self.vars["insert_space"].get()),
            "model": self.vars["model"].get(),
        }
        # validate the hotkey before committing
        try:
            from pynput import keyboard
            keyboard.HotKey.parse(new["hotkey"])
        except Exception:
            self.save_hint.config(text="Invalid hotkey format", fg=REC)
            return

        model_changed = new["model"] != self.cfg["model"]
        self.cfg.update(new)
        save_config(self.cfg)

        # rebuild the pieces that read config at construction time
        from core import Beeper, Recorder, Typist
        self.core.beeper = Beeper(self.cfg["sound_feedback"])
        self.core.recorder = Recorder(self.cfg["sample_rate"])
        self.core.typist = Typist(self.cfg)

        # re-register the (possibly new) hotkey
        if self.hotkeys is not None:
            self.hotkeys.stop()
            self.hotkeys = HotkeyManager(self.cfg, self.core,
                                         on_quit=lambda: self.events.put(("quit", None)))
            try:
                self.hotkeys.start()
            except Exception as e:
                self.save_hint.config(text=f"Hotkey error: {e}", fg=REC)

        if model_changed:
            self.model_sig = self._model_sig()
            self.save_hint.config(text="Saved — reloading model…", fg=AMBER)
            threading.Thread(target=self._reload_model, daemon=True).start()
        else:
            self.save_hint.config(text="Saved ✓", fg=GREEN)
            self.root.after(1600, lambda: self.save_hint.config(text=""))

    def _reload_model(self):
        try:
            self.core.load_model()
            self.events.put(("saved_model", None))
        except Exception as e:
            self.events.put(("error", f"Model reload failed: {e}"))

    # ── event pump (applies engine callbacks on the UI thread) ───────────────
    def _pump(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    self._set_state(payload)
                elif kind == "transcript":
                    self._show_transcript(payload)
                elif kind == "deliver":
                    self.core.deliver(payload)   # on the main thread — safe
                elif kind == "error":
                    self.status_lbl.config(text=payload, fg=REC)
                elif kind == "saved_model":
                    self.save_hint.config(text="Saved ✓", fg=GREEN)
                    self.root.after(1600, lambda: self.save_hint.config(text=""))
                elif kind == "window":
                    self._toggle_window()
                elif kind == "quit":
                    self._quit()
        except queue.Empty:
            pass
        self.root.after(60, self._pump)

    def _toggle_window(self):
        """Show/hide the settings window on demand (window_hotkey). Showing it is
        the one time we deliberately come to the foreground."""
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.root.lift()
            try:
                from AppKit import NSApplication
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            except Exception:
                pass
        else:
            self.root.withdraw()

    def _quit(self):
        try:
            if self.hotkeys is not None:
                self.hotkeys.stop()
        finally:
            self.root.destroy()
            sys.exit(0)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
