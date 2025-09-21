#!/usr/bin/env bash
set -e

# === Einstellungen ===
APPDIR="/home/robby/Apps"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# === Logdatei im Skriptverzeichnis ===
LOGFILE="$SCRIPT_DIR/lmstudio_autostart.log"

# === Argumente parsen (Debug-Flag, Modellname) ===
DEBUG_FLAG=0
MODEL=""
while [ $# -gt 0 ]; do
    case "$1" in
        --debug|-d)
            DEBUG_FLAG=1; shift ;;
        --)
            shift; break ;;
        -*)
            echo "Unbekannte Option: $1" ; shift ;;
        *)
            if [ -z "$MODEL" ]; then MODEL="$1"; shift; else shift; fi ;;
    esac
done

if [ "${LM_AUTOSTART_DEBUG:-0}" = "1" ]; then
    DEBUG_FLAG=1
fi

# === Logging konfigurieren ===
     : > "$LOGFILE"
if [ "$DEBUG_FLAG" = "1" ]; then
    exec > >(tee -a >(sed 's/\x1b\[[0-9;]*m//g' >> "$LOGFILE")) \
         2> >(tee -a >(sed 's/\x1b\[[0-9;]*m//g' >> "$LOGFILE") >&2)
    set -x
    echo "[DEBUG] Terminal- und Log-Ausgabe aktiviert. Log: $LOGFILE"
else
    exec > >(sed 's/\x1b\[[0-9;]*m//g' >> "$LOGFILE") 2>&1
fi
LMSTUDIO_APPIMAGE=$(ls -t "$APPDIR"/LM-Studio-*.AppImage | head -n 1)
LMS_CLI="/home/robby/.lmstudio/bin/lms"
GPU="1.0"
MAX_WAIT=30
INTERVAL=1
WAIT_FOR_LMS=60
LMS_RETRIES=3
LMS_RETRY_SLEEP=5

# === Modellname (falls nicht via Args gesetzt bleibt er leer) ===

export LMSTUDIO_DISABLE_AUTO_LAUNCH=true

# === Abhängigkeiten prüfen (interaktiv vorschlagen) ===
have() { command -v "$1" >/dev/null 2>&1; }

SESSION_TYPE="${XDG_SESSION_TYPE:-}"
IS_WAYLAND=false; [ "${SESSION_TYPE,,}" = "wayland" ] && IS_WAYLAND=true || true

if [ ! -f "$LMSTUDIO_APPIMAGE" ]; then
    echo "❌ Keine LM Studio AppImage gefunden in $APPDIR"
    exit 1
fi

is_running=false
if command -v pgrep >/dev/null 2>&1; then
    if pgrep -f "$(basename "$LMSTUDIO_APPIMAGE")" >/dev/null 2>&1 || pgrep -f "LM Studio" >/dev/null 2>&1; then
        is_running=true
    fi
fi

if $is_running; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') 🟢 LM Studio läuft bereits – überspringe Start."
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') 🚀 Starte LM Studio GUI: $LMSTUDIO_APPIMAGE"
    "$LMSTUDIO_APPIMAGE" &
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') 🔍 Warte auf LM Studio-Fenster..."
SECONDS_WAITED=0
WINDOW_ID=""

if ! $IS_WAYLAND && have xdotool; then
    while [ "$SECONDS_WAITED" -lt "$MAX_WAIT" ]; do
        WINDOW_ID=$(xdotool search --onlyvisible --name "LM Studio" | head -n 1)
        if [ -n "$WINDOW_ID" ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ Fenster gefunden: $WINDOW_ID – minimiere..."
            xdotool windowminimize "$WINDOW_ID" || true
            break
        fi
        sleep "$INTERVAL"
        SECONDS_WAITED=$((SECONDS_WAITED + INTERVAL))
    done
    if [ -z "$WINDOW_ID" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ Fenster nicht gefunden – Minimierung übersprungen."
    fi
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') ℹ️ Fenster-Minimierung übersprungen (Wayland oder xdotool nicht verfügbar)."
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') ⏳ Warte 10 Sekunden, bis LM Studio bereit ist..."
sleep 10

# === Modell laden, wenn übergeben ===
if [ -n "$MODEL" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') 📦 Lade Modell: $MODEL ..."
    SECONDS_WAITED=0
    LMS_CMD=""
    while [ "$SECONDS_WAITED" -lt "$WAIT_FOR_LMS" ]; do
        if [ -x "$LMS_CLI" ]; then
            LMS_CMD="$LMS_CLI"; break
        elif have lms; then
            LMS_CMD="$(command -v lms)"; break
        fi
        sleep 1; SECONDS_WAITED=$((SECONDS_WAITED + 1))
    done

    if [ -z "$LMS_CMD" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') ❌ lms-CLI nicht gefunden nach ${WAIT_FOR_LMS}s – überspringe Laden."
        MODEL="fehler-modell"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') 🔧 Verwende lms-CLI: $LMS_CMD"
        ATTEMPT=1
        LOAD_OK=false
        while [ "$ATTEMPT" -le "$LMS_RETRIES" ]; do
            echo "$(date '+%Y-%m-%d %H:%M:%S') ▶️ Lade-Versuch $ATTEMPT/$LMS_RETRIES: '$MODEL' mit GPU=$GPU"
            if "$LMS_CMD" load "$MODEL" --gpu="$GPU"; then
                LOAD_OK=true; break
            fi
            sleep "$LMS_RETRY_SLEEP"; ATTEMPT=$((ATTEMPT + 1))
        done

        if ! $LOAD_OK; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ Laden mit GPU=$GPU fehlgeschlagen – versuche CPU-Fallback (GPU=0.0)."
            if "$LMS_CMD" load "$MODEL" --gpu="0.0"; then
                LOAD_OK=true; GPU="0.0"
            fi
        fi

        if $LOAD_OK; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ Modell geladen (GPU=$GPU)!"
            if have notify-send; then
                notify-send -i dialog-information -t 5000 "LM Studio" "✅ Modell '$MODEL' erfolgreich geladen! (GPU=$GPU)" || true
            fi
        else
            echo "$(date '+%Y-%m-%d %H:%M:%S') ❌ Modell '$MODEL' konnte nicht geladen werden – überspringe."
            MODEL="fehler-modell"
        fi
    fi
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') ℹ️ Kein Modell übergeben – überspringe Laden."
    MODEL="kein-modell"
fi

# === Starte Tray-Monitor mit Modellname (auch Platzhalter) ===
echo "$(date '+%Y-%m-%d %H:%M:%S') 🐍 Starte Tray-Monitor: $SCRIPT_DIR/lmstudio_tray.py mit Modell '$MODEL'"
if have python3; then
    python3 "$SCRIPT_DIR/lmstudio_tray.py" "$MODEL" &
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ Tray nicht gestartet – python3 nicht gefunden."
fi

