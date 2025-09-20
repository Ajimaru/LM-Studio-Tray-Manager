#!/usr/bin/env bash
set -e

# === Einstellungen ===
APPDIR="/home/robby/Apps"
SCRIPT_DIR="$APPDIR/LM-Studio"
LMSTUDIO_APPIMAGE=$(ls -t "$APPDIR"/LM-Studio-*.AppImage | head -n 1)
LMS_CLI="/home/robby/.lmstudio/bin/lms"
GPU="1.0"
MAX_WAIT=30
INTERVAL=1

# === Modellname aus Argument oder leer ===
MODEL="${1:-}"

export LMSTUDIO_DISABLE_AUTO_LAUNCH=true

if [ ! -f "$LMSTUDIO_APPIMAGE" ]; then
    echo "❌ Keine LM Studio AppImage gefunden in $APPDIR"
    exit 1
fi

echo "🚀 Starte LM Studio GUI: $LMSTUDIO_APPIMAGE"
"$LMSTUDIO_APPIMAGE" &

echo "🔍 Warte auf LM Studio-Fenster..."
SECONDS_WAITED=0
WINDOW_ID=""

while [ "$SECONDS_WAITED" -lt "$MAX_WAIT" ]; do
    WINDOW_ID=$(xdotool search --onlyvisible --name "LM Studio" | head -n 1)
    if [ -n "$WINDOW_ID" ]; then
        echo "✅ Fenster gefunden: $WINDOW_ID – minimiere..."
        xdotool windowminimize "$WINDOW_ID"
        break
    fi
    sleep "$INTERVAL"
    SECONDS_WAITED=$((SECONDS_WAITED + INTERVAL))
done

if [ -z "$WINDOW_ID" ]; then
    echo "⚠️ Fenster nicht gefunden – Minimierung übersprungen."
fi

echo "⏳ Warte 10 Sekunden, bis LM Studio bereit ist..."
sleep 10

# === Modell laden, wenn übergeben ===
if [ -n "$MODEL" ]; then
    echo "📦 Lade Modell: $MODEL ..."
    "$LMS_CLI" load "$MODEL" --gpu="$GPU"
    echo "✅ Modell geladen!"
    notify-send -i dialog-information -t 5000 "LM Studio" "✅ Modell '$MODEL' erfolgreich geladen!"
else
    echo "ℹ️ Kein Modell übergeben – überspringe Laden."
    MODEL="kein-modell"
fi

# === Starte Tray-Monitor mit Modellname (auch Platzhalter) ===
python3 "$SCRIPT_DIR/lmstudio_tray.py" "$MODEL" &

