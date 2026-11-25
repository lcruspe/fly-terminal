#!/bin/sh
set -eu
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Applications/FlyAudioCapture.app"
BIN="$APP/Contents/MacOS/FlyAudioCapture"
mkdir -p "$APP/Contents/MacOS" "$HOME/.local/share/fly-terminal"
if [ ! -x "$BIN" ] || [ "$DIR/fly-audio-tap.m" -nt "$BIN" ] || [ "$DIR/build-audio-tap.sh" -nt "$BIN" ]; then
    OPUS_PREFIX="$(/opt/homebrew/bin/brew --prefix opus)"
    cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>ai.kruspe.fly-terminal.audio</string>
<key>CFBundleExecutable</key><string>FlyAudioCapture</string>
<key>CFBundleName</key><string>Fly Audio Capture</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>LSUIElement</key><true/>
<key>NSAudioCaptureUsageDescription</key><string>Stream system audio to your authenticated Fly Terminal remote session.</string>
</dict></plist>
PLIST
    tmp="$BIN.tmp.$$"
    trap 'rm -f "$tmp"' EXIT
    clang -fobjc-arc -O2 -framework Foundation -framework CoreAudio -framework AVFoundation -I"$OPUS_PREFIX/include" -L"$OPUS_PREFIX/lib" -lopus "$DIR/fly-audio-tap.m" -o "$tmp"
    mv -f "$tmp" "$BIN"
    codesign --force --sign - "$APP"
fi
