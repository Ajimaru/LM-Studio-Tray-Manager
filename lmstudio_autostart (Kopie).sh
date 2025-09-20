#!/usr/bin/env bash
set -e

# === Einstellungen ===
LMSTUDIO_APPIMAGE="/home/robby/Apps/LM-Studio-0.3.26-6-x64_b01891d0a7ee588a55f9f51c1fec843b.AppImage"
LMS_CLI="/home/robby/.lmstudio/bin/lms"
MODEL="deepseek-r1-0528-qwen3-8b"
GPU="1.0"
MAX_WAIT=30
INTERVAL=1

# === Umgebungsvariable setzen ===
export LMSTUDIO_DISABLE_AUTO_LAUNCH=true

# === LM Studio starten ===
echo "🚀 Starte LM Studio GUI..."
"$LMSTUDIO_APPIMAGE" &

# === Fenster erkennen und minimieren ===
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

# === Warten, bis LM Studio bereit ist ===
echo "⏳ Warte 10 Sekunden, bis LM Studio bereit ist..."
sleep 10

# === Modell laden ===
echo "📦 Lade Modell: $MODEL ..."
"$LMS_CLI" load "$MODEL" --gpu="$GPU"

echo "✅ Modell geladen!"

# === Desktop-Benachrichtigung ===
notify-send -i dialog-information -t 5000 "LM Studio" "✅ Modell '$MODEL' erfolgreich geladen!"

