# 🎙️ Whisperbox — Local Speech-to-Text

**Speak instead of type. Anywhere on your Mac. Nothing ever leaves your machine.**

Whisperbox is a tiny, private **speech-to-text** engine that turns your voice
into text in *any* app. Press a hotkey, talk, and your words appear right where
your cursor is. It runs [OpenAI's Whisper](https://github.com/openai/whisper)
locally via [faster-whisper](https://github.com/SYSTRAN/faster-whisper), so
your voice is transcribed **entirely on-device** — no cloud, no account, no
subscription, no network calls after the one-time model download.

It runs as a **background app**: no window, no Dock icon, no Terminal. Just you,
your keyboard-free voice, and text that lands wherever you're already working.

## What it's great for

- ✍️ **Writing, hands-free.** Draft emails, notes, docs, messages, and code
  comments by talking — far faster than typing, and easier on your hands.
- 🌐 **Searching the web with your voice.** Click any browser search bar or
  address field, speak your query, done — no typing.
- 🤖 **Talking to your AI agents keyboard-free.** Dictate long prompts straight
  into ChatGPT, Claude, Cursor, or any chat box. Perfect for thinking out loud
  and letting the AI do the rest.
- 💬 **Chat & Slack.** Fire off replies by voice without touching the keyboard.

Think of it as the dictation feature your OS should have shipped — but open,
offline, and completely yours to reprogram.

---

## Why you might like it

- 🔒 **100% private & offline.** Audio is processed on your Mac and immediately
  discarded. Pull your Wi-Fi and it still works.
- ⌨️ **Works everywhere.** A global hotkey dictates into whatever app is focused
  — browser, editor, chat, AI agent — not just one text box.
- 🫥 **Truly seamless.** Runs in the background and never steals focus, so text
  flows straight into the field you're already in.
- 🧠 **Real Whisper accuracy**, from a featherweight `tiny` model up to
  `large-v3`, tunable for your machine.
- 🎛️ **Fully programmable.** Change the hotkey, switch push-to-talk vs.
  toggle, pick clipboard/typing/both — from a settings panel or a JSON file.
- 🪶 **Lightweight.** No PyTorch, no Electron. Just Python, ~500 MB for the
  default model.

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
./setup.sh              # one-time: creates a venv, installs deps
./build-app.sh          # one-time: builds Whisperbox.app
open Whisperbox.app     # runs silently in the background
```

The first launch downloads the Whisper model once (~500 MB for `small.en`);
after that it's fully offline. Then just:

1. Click into any text field
2. Press **Ctrl + Shift + D**, talk, press **Ctrl + Shift + D** again
3. Your words type themselves in, right at the cursor

It runs as a **background app** — no window, no Dock icon, and it never steals
focus. Press **Ctrl+Shift+W** for Settings, **Ctrl+Shift+Q** to quit.

> Prefer a visible window? Set `"show_window": true` in `config.json`, or run
> `./run.sh` (window) / `./run-cli.sh` (terminal only).

### macOS permissions (one time)

The mic, typing, and the global hotkey each need permission under
**System Settings → Privacy & Security**. Grant these to **Whisperbox** (it may
appear as "Python") — or to **Terminal** if you launch via `./run.sh` — then
relaunch:

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
