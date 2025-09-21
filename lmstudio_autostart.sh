#!/usr/bin/env bash
set -e

# === Logdatei im aktuellen Verzeichnis ===
LOGFILE="$(pwd)/lmstudio_autostart.log"
exec > >(sed 's/\x1b\[[0-9;]*m//g' > "$LOGFILE") 2>&1

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

# === Abhängigkeiten prüfen (interaktiv vorschlagen) ===
have() { command -v "$1" >/dev/null 2>&1; }
ask_install() {
    local pkgs=("$@")
    if have apt-get; then
        echo "Vorschlag: sudo apt-get update && sudo apt-get install -y ${pkgs[*]}"
        if [ -t 0 ]; then
            read -r -p "Jetzt installieren? [J/n] " REPLY || true
            REPLY=${REPLY:-J}
            if [[ "$REPLY" =~ ^[JjYy]$ ]]; then
                sudo apt-get update || true
                sudo apt-get install -y "${pkgs[@]}" || true
            fi
        fi
    else
        echo "Kein apt-get gefunden – bitte installiere manuell: ${pkgs[*]}"
    fi
}

SESSION_TYPE="${XDG_SESSION_TYPE:-}"
IS_WAYLAND=false; [ "${SESSION_TYPE,,}" = "wayland" ] && IS_WAYLAND=true || true

# Pflicht: python3 (für Tray), optional notify-send für Benachrichtigung
if ! have python3; then
    echo "❗ python3 fehlt."
    ask_install python3
fi
if ! have notify-send; then
    echo "ℹ️ notify-send fehlt (libnotify-bin)."; ask_install libnotify-bin
fi

# Eingabetools
if $IS_WAYLAND; then
    if ! have wtype; then
        echo "ℹ️ Wayland erkannt – für Text-/Tastatureingaben ist 'wtype' hilfreich."; ask_install wtype
    fi
else
    if ! have xdotool; then
        echo "ℹ️ X11 erkannt – 'xdotool' ermöglicht Minimieren/Eingaben."; ask_install xdotool
    fi
    if ! have wmctrl; then
        echo "ℹ️ Für Fenstersteuerung ist 'wmctrl' nützlich."; ask_install wmctrl
    fi
fi

if [ ! -f "$LMSTUDIO_APPIMAGE" ]; then
    echo "❌ Keine LM Studio AppImage gefunden in $APPDIR"
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') 🚀 Starte LM Studio GUI: $LMSTUDIO_APPIMAGE"
"$LMSTUDIO_APPIMAGE" &

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
    echo "$(date '+%Y-%m-%d %H:%M:%S') ℹ️ Wayland oder kein xdotool – Fenster-Minimierung wird übersprungen."
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') ⏳ Warte 10 Sekunden, bis LM Studio bereit ist..."
sleep 10

# === Modell laden, wenn übergeben ===
if [ -n "$MODEL" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') 📦 Lade Modell: $MODEL ..."
    if [ -x "$LMS_CLI" ]; then
        LMS_CMD="$LMS_CLI"
    elif have lms; then
        LMS_CMD="$(command -v lms)"
    else
        LMS_CMD=""
    fi

    if [ -n "$LMS_CMD" ] && "$LMS_CMD" load "$MODEL" --gpu="$GPU"; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ Modell geladen!"
        if have notify-send; then
            notify-send -i dialog-information -t 5000 "LM Studio" "✅ Modell '$MODEL' erfolgreich geladen!" || true
        fi
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') ❌ Modell '$MODEL' konnte nicht geladen werden – überspringe."
        MODEL="fehler-modell"
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
    echo "⚠️ Tray nicht gestartet – python3 fehlt."
fi

