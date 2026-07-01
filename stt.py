#!/usr/bin/env python3
"""
Command-line front-end for the local speech-to-text engine.

Press the programmable hotkey to start talking, press it again to stop (toggle
mode) — audio is transcribed on-device and the text is copied to your clipboard
and/or typed at the cursor. Nothing leaves your machine.

For the graphical version, run:  python gui.py   (or ./run.sh)
Settings live in config.json.
"""

import threading

from core import HotkeyManager, SttCore, load_config


def main():
    cfg = load_config()

    def on_status(state):
        labels = {
            "loading": "[stt] Loading model...",
            "recording": ("[stt] 🎙  Recording... "
                          + ("(press hotkey again to stop)" if cfg["mode"] == "toggle"
                             else "(release to stop)")),
            "transcribing": "[stt] ⏳ Transcribing...",
            "idle": "[stt] Ready.",
        }
        if state in labels:
            print(labels[state])

    def on_transcript(text):
        print(f"[stt] {text}" if text else "[stt] (nothing transcribed)")

    def on_error(msg):
        print(f"[stt] {msg}")

    core = SttCore(cfg, on_status=on_status, on_transcript=on_transcript, on_error=on_error)
    core.load_model()

    stop_event = threading.Event()
    hotkeys = HotkeyManager(cfg, core, on_quit=stop_event.set)
    hotkeys.start()

    print("\n" + "=" * 60)
    print("  Local Speech-to-Text  —  ready")
    print(f"  Hotkey : {cfg['hotkey']}   ({cfg['mode']} mode)")
    print(f"  Quit   : {cfg['quit_hotkey']}")
    print(f"  Output : {cfg['output']}")
    print("=" * 60 + "\n")

    try:
        stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        hotkeys.stop()
        print("\n[stt] Quitting.")


if __name__ == "__main__":
    main()
