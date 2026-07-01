# 🎙️ Whisperbox — Local Speech-to-Text

**Talk to your Mac. It types back. Nothing ever leaves your machine.**

Whisperbox is a tiny, private dictation app. Press a hotkey from *anywhere* —
your editor, your browser, a Slack box, a terminal — start talking, press it
again, and your words appear as text on your clipboard and at your cursor. It
runs [OpenAI's Whisper](https://github.com/openai/whisper) locally via
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), so your voice is
transcribed **entirely on-device**. No cloud, no account, no subscription, no
network calls after the one-time model download.

Think of it as the dictation feature your OS should have shipped — but open,
offline, and completely yours to reprogram.

---

## Why you might like it

- 🔒 **100% private & offline.** Audio is processed on your Mac and immediately
  discarded. Pull your Wi-Fi and it still works.
- ⌨️ **A hotkey that works everywhere.** A global shortcut dictates into
  whatever app is focused — not just one text box.
- 🧠 **Real Whisper accuracy**, from a featherweight `tiny` model up to
  `large-v3`, tunable for your machine.
- 🎛️ **Fully programmable.** Change the hotkey, switch push-to-talk vs.
  toggle, pick clipboard/typing/both — from a settings panel or a JSON file.
- 🪶 **Lightweight.** No PyTorch, no Electron. Just Python, ~500 MB for the
  default model, and a native little window.
- 🆓 **Free and hackable.** ~500 lines of readable Python. Bend it to your will.

---

## The app

A small dark window with everything front-and-center:

| | |
|---|---|
| 🎙️ **Big mic button** | Click to start/stop. Glows blue when idle, **pulses red** while recording, turns amber while transcribing. |
| 📝 **Live transcript** | See your last dictation with a one-click **Copy**. |
| ⚙️ **Inline settings** | Rebind the hotkey, switch modes, change the model — no file editing, no restart. |

Prefer the terminal? There's a headless CLI mode too.

### ✨ Dictate straight into any text field

The whole point: put your cursor in *any* text field — an email, a code
comment, a chat box — hit your hotkey, and speak. A slim **floating pill**
slides up from the bottom of the screen with a **live waveform** so you know
it's listening, then shows a shimmer while it transcribes. Your words are
inserted **right at the caret**, appended cleanly to whatever you'd already
typed. The pill never steals focus, so your text field stays active the whole
time — then it quietly disappears.

```text
        ┌─────────────────────────────────────┐
        │  ●   ▁▃▅▇▆▄▂▁▂▄▆▇▅▃▁▂▄▅▃▂            │   ← floating pill: live waveform
        └─────────────────────────────────────┘
```

Toggle the pill and the smart leading-space behavior in **⚙ Settings**.

---

## Quickstart (macOS)

```bash
git clone https://github.com/JKobygold/whisperbox.git
cd whisperbox
./setup.sh        # one-time: creates a venv, installs deps
./run.sh          # launches the app
```

The first launch downloads the Whisper model once (~500 MB for `small.en`);
after that it's fully offline. Then just:

1. Click the mic (or press **Ctrl + Alt + Space**)
2. Talk
3. Press again — your text lands on the clipboard and types itself in

> Prefer no window? `./run-cli.sh` runs it in the terminal.

### macOS permissions (one time)

Global hotkeys, the microphone, and typing at the cursor each need permission.
Grant these to your **Terminal** app under
**System Settings → Privacy & Security**, then relaunch:

- **Microphone** — to hear you
- **Accessibility** — to type text and register the hotkey
- **Input Monitoring** — for the global hotkey listener

---

## Make it yours

Everything is driven by [`config.json`](config.json) (or the ⚙️ Settings panel).

```json
{
  "hotkey": "<ctrl>+<alt>+<space>",
  "mode": "toggle",
  "output": "both",
  "overlay": true,
  "insert_space": true,
  "auto_paste": false,
  "model": "small.en",
  "language": "en",
  "compute_type": "int8"
}
```

### `hotkey` — your programmable command
Angle-bracket the modifiers and special keys; bare letters/digits are literal:

- `"<cmd>+<shift>+d"`
- `"<ctrl>+<alt>+<space>"`
- `"<f9>"`

Modifiers: `<cmd>` (⌘) · `<ctrl>` · `<alt>` (⌥) · `<shift>`. Special keys such
as space/tab/enter must be wrapped: `<space>`, `<tab>`, `<enter>`.

### `mode`

- `"toggle"` — press once to start, again to stop *(default)*
- `"hold"` — push-to-talk: hold to record, release to transcribe

### `output`

- `"clipboard"` · `"type"` · `"both"` *(default)*
- `"type"`/`"both"` insert at the cursor in the focused field — this is what
  lets you dictate straight into any app.
- Set `"auto_paste": true` to auto-press ⌘V after copying.

### `overlay` & `insert_space`

- `overlay` *(default `true`)* — show the floating waveform pill while dictating.
- `insert_space` *(default `true`)* — prepend a space so dictated text appends
  cleanly to what you've already typed.

### `model` — accuracy vs. speed
`tiny(.en)` · `base(.en)` · `small(.en)` *(default)* · `medium(.en)` ·
`large-v3`. Drop `.en` for multilingual. Bigger = more accurate, slower, more
RAM. `compute_type` trades speed for precision: `int8` (fastest) →
`int8_float16` → `float16`.

---

## How it works

```
 mic  ──▶  sounddevice  ──▶  faster-whisper (Whisper, local)  ──▶  clipboard / keystrokes
                    ▲
        global hotkey (pynput) toggles recording
```

- [`core.py`](core.py) — the engine: microphone capture, the Whisper model,
  output delivery, and the programmable global hotkey, exposed through simple
  status/transcript callbacks.
- [`gui.py`](gui.py) — the native Tkinter window.
- [`stt.py`](stt.py) — the terminal front-end.

Both front-ends share the same engine, so the app and the CLI behave
identically.

---

## Troubleshooting

- **Hotkey does nothing** → grant Accessibility + Input Monitoring, then relaunch.
- **Silence / no transcript** → grant Microphone; check your input device in
  System Settings → Sound.
- **Clipboard works but it won't type** → grant Accessibility.
- **Slow first launch** → that's the one-time model download; later runs are fast.

---

## Roadmap ideas

Pull requests welcome — some fun directions:

- A menu-bar / tray icon so there's no window at all
- Streaming (live) transcription as you speak
- A standalone double-clickable `.app` bundle
- Linux & Windows support (the engine is cross-platform; hotkeys/audio need glue)

---

## License

MIT — do whatever you like. See [LICENSE](LICENSE).

---

*Built for people who'd rather talk than type, and who'd rather their voice
stay on their own machine.*
