#!/usr/bin/env bash
set -e

# === Einstellungen ===
APPDIR="/home/robby/Apps"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# === Logdatei im Skriptverzeichnis ===
LOGFILE="$SCRIPT_DIR/lmstudio_autostart.log"

# === Hilfe ===
usage() {
    cat <<EOF
Benutzung: $(basename "$0") [OPTIONEN]

Startet LM Studio (AppImage), minimiert das Fenster unter X11, lädt optional ein Modell über die lms-CLI
mit GPU-Fallback und startet den Tray-Monitor. Die Logdatei wird pro Lauf neu erstellt:
    $LOGFILE

Optionen:
    -d, --debug       Debug-Ausgabe und Bash-Trace aktivieren (auch Terminalausgabe)
    -h, --help        Diese Hilfe anzeigen und beenden
    -L, --list-models Lokale Modelle auflisten (kein LM Studio Start)
    -m, --model NAME  Angegebenes Modell laden (wenn NAME fehlt, wird kein Modell geladen)

Umgebungsvariablen:
    LM_AUTOSTART_DEBUG=1   Debug-Modus erzwingen (entspricht --debug)

Exit-Codes:
    0  Erfolg
    1  AppImage nicht gefunden
    2  Ungültige Option/Benutzung

Beispiele:
    $(basename "$0")
    $(basename "$0") --debug
    $(basename "$0") --model qwen2.5:7b-instruct
    $(basename "$0") -m qwen2.5:7b-instruct
    $(basename "$0") -m   # Flag ohne Namen: lädt kein Modell, Rest läuft normal
EOF
}

# === Lokale Modelle auflisten (ohne LM Studio zu starten) ===
list_models() {
    echo "Lokale Modelle (ohne LM Studio Start):"
    local found=0

    local LMS_CANDIDATES=("$HOME/.lmstudio/bin/lms")
    if command -v lms >/dev/null 2>&1; then LMS_CANDIDATES+=("$(command -v lms)"); fi

    for cand in "${LMS_CANDIDATES[@]}"; do
        [ -n "$cand" ] && [ -x "$cand" ] || continue
        local out rc
        set +e
        out="$("$cand" models list 2>/dev/null)"; rc=$?
        if [ $rc -ne 0 ] || [ -z "$out" ]; then
            out="$("$cand" list 2>/dev/null)"; rc=$?
        fi
        set -e
        if [ $rc -eq 0 ] && [ -n "$out" ]; then
            echo "Quelle: lms ($cand)"
            echo "$out"
            found=1
            break
        fi
    done

    local dirs=(
        "$HOME/.cache/lm-studio"
        "$HOME/.cache/LM-Studio"
        "$HOME/.lmstudio/models"
        "$HOME/LM Studio/models"
        "$SCRIPT_DIR/models"
    )
    for dir in "${dirs[@]}"; do
        [ -d "$dir" ] || continue
        local -a files=()
        set +e
        mapfile -t files < <(find "$dir" -maxdepth 6 -type f \( -iname "*.gguf" -o -iname "*.bin" -o -iname "*.safetensors" \) 2>/dev/null)
        set -e
        if [ ${#files[@]} -gt 0 ]; then
            echo "Quelle: $dir"
            for f in "${files[@]}"; do
                echo " - $(basename "$f")  [$f]"
            done
            found=1
        fi
    done

    if [ "$found" -eq 0 ]; then
        echo "Keine lokalen Modelle gefunden."
        return 3
    fi
    return 0
}

# === Argumente parsen (Debug-Flag, Modellname) ===
DEBUG_FLAG=0
MODEL=""
LIST_MODELS=0
while [ $# -gt 0 ]; do
    case "$1" in
        --debug|-d)
            DEBUG_FLAG=1; shift ;;
                --help|-h)
                        usage; exit 0 ;;
        --list-models|-L)
            LIST_MODELS=1; shift ;;
        --model|-m)
            if [ -n "${2:-}" ] && [ "${2#-}" != "$2" ]; then
                shift
            elif [ -n "${2:-}" ]; then
                MODEL="$2"; shift 2
            else
                shift
            fi ;;
        --)
            shift; break ;;
        -*)
                        echo "Fehler: Unbekannte Option: $1" >&2
                        usage >&2
            exit 2 ;;
        *)
            if [ "$DEBUG_FLAG" = "1" ] || [ "${LM_AUTOSTART_DEBUG:-0}" = "1" ]; then
                echo "Hinweis: Positionsargument '$1' wird ignoriert. Bitte --model/-m NAME verwenden." >&2
            fi
            shift ;;
    esac
done

if [ "$LIST_MODELS" = "1" ]; then
    list_models
    exit $?
fi

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

