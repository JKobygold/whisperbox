#!/bin/bash
# Builds Whisperbox.app — a background (menu-less, Dock-less) launcher so the
# app runs with no Terminal window and never steals focus from your text field.
set -e
cd "$(dirname "$0")"
APP="Whisperbox.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Whisperbox</string>
  <key>CFBundleDisplayName</key><string>Whisperbox</string>
  <key>CFBundleIdentifier</key><string>com.jkobygold.whisperbox</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleExecutable</key><string>whisperbox</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Whisperbox transcribes your speech locally, on-device.</string>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/whisperbox" <<'SH'
#!/bin/bash
# Whisperbox background launcher. Runs native arm64 to match the venv wheels.
DIR="$HOME/Projects/local-stt"
cd "$DIR" || exit 1
source .venv/bin/activate
if /usr/bin/arch -arm64 true 2>/dev/null; then
  exec /usr/bin/arch -arm64 python gui.py >/tmp/whisperbox.log 2>&1
else
  exec python gui.py >/tmp/whisperbox.log 2>&1
fi
SH
chmod +x "$APP/Contents/MacOS/whisperbox"

echo "Built $APP"
echo "Launch it with:  open $APP    (or double-click it in Finder)"
echo "It runs in the background — no Dock icon, no Terminal."
