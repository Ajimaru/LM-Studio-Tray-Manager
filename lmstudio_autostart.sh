#!/usr/bin/env bash
set -e

# === Einstellungen ===
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# === Logdatei im Skriptverzeichnis ===
LOGFILE="$SCRIPT_DIR/lmstudio_autostart.log"

# === Konfiguration laden oder Setup ===
CONFIG_FILE="$SCRIPT_DIR/config.json"

setup_config() {
    echo "Konfiguration nicht gefunden. Setup wird gestartet."
    echo "Geben Sie den Pfad zum Ordner ein, in dem die LM Studio AppImage gespeichert ist (Tab für Autovervollständigung):"
    read -e -p "AppImage-Ordner: " APPDIR_INPUT
    if [ -z "$APPDIR_INPUT" ]; then
        echo "Fehler: Pfad darf nicht leer sein." >&2
        exit 1
    fi
    if [ ! -d "$APPDIR_INPUT" ]; then
        echo "Fehler: Ordner existiert nicht." >&2
        exit 1
    fi
    echo "{\"appdir\": \"$APPDIR_INPUT\"}" > "$CONFIG_FILE"
    echo "Konfiguration gespeichert in $CONFIG_FILE"
}

if [ ! -f "$CONFIG_FILE" ]; then
    setup_config
fi

APPDIR=$(grep -o '"appdir": "[^"]*"' "$CONFIG_FILE" | sed 's/"appdir": "//;s/"//')

# === Abhängigkeiten prüfen ===
check_dependencies() {
    local missing=()
    local to_install=()

    if ! command -v xdotool >/dev/null 2>&1; then
        missing+=("xdotool")
        to_install+=("sudo apt install xdotool")
    fi
    if ! command -v curl >/dev/null 2>&1; then
        missing+=("curl")
        to_install+=("sudo apt install curl")
    fi
    if ! command -v notify-send >/dev/null 2>&1; then
        missing+=("notify-send (libnotify)")
        to_install+=("sudo apt install libnotify-bin")
    fi
    if ! command -v python3 >/dev/null 2>&1; then
        missing+=("python3")
        to_install+=("sudo apt install python3")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        echo "Folgende Abhängigkeiten fehlen: ${missing[*]}"
        echo "Möchten Sie sie installieren? (J/n) [J]"
        read -r answer
        answer=${answer:-J}
        if [[ "$answer" =~ ^[jJyYJ] ]]; then
            for cmd in "${to_install[@]}"; do
                echo "Führe: $cmd"
                eval "$cmd"
            done
        else
            echo "Abhängigkeiten sind erforderlich. Beende."
            exit 1
        fi
    fi

    if ! ls "$APPDIR"/LM-Studio-*.AppImage >/dev/null 2>&1; then
        echo "LM Studio AppImage nicht gefunden in $APPDIR."
        echo "Möchten Sie LM Studio herunterladen? (J/n) [J]"
        read -r answer
        answer=${answer:-J}
        if [[ "$answer" =~ ^[jJyYJ] ]]; then
            echo "Öffne Browser für Download..."
            xdg-open "https://lmstudio.ai/" 2>/dev/null || echo "Bitte öffnen Sie https://lmstudio.ai/ manuell."
            echo "Nach dem Download legen Sie die AppImage in $APPDIR und führen Sie das Skript erneut aus."
            exit 0
        else
            echo "LM Studio AppImage ist erforderlich. Beende."
            exit 1
        fi
    fi
}

check_dependencies

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
    -L, --list-models Lokale Modelle auflisten; bei TTY: interaktive Auswahl mit 30s Auto-Skip (kein LM Studio Start vor Auswahl)
    -m, --model NAME  Angegebenes Modell laden (wenn NAME fehlt, wird kein Modell geladen)

Umgebungsvariablen:
    LM_AUTOSTART_DEBUG=1            Debug-Modus erzwingen (entspricht --debug)
    LM_AUTOSTART_SELECT_TIMEOUT=30  Timeout (Sekunden) für interaktive -L Auswahl; nach Ablauf wird automatisch "Skip" gewählt

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
    $(basename "$0") -L   # Interaktive Modellauswahl (bei TTY) oder reine Liste (ohne TTY)
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
MODEL_EXPLICIT=0
SELECT_TIMEOUT="${LM_AUTOSTART_SELECT_TIMEOUT:-30}"
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
                MODEL="$2"; MODEL_EXPLICIT=1; shift 2
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

countdown_prompt() {
    local timeout="$1"; shift
    local prompt="$*"
    local t pid
    t="$timeout"
    {
        while [ "$t" -gt 0 ]; do
            printf "\r%s (Auto-Skip in %2ds) " "$prompt" "$t"
            sleep 1
            t=$((t-1))
        done
        printf "\r%s (Auto-Skip in  0s) " "$prompt"
    } >&2 &
    echo $!
}

if [ "$LIST_MODELS" = "1" ]; then
    if [ -t 0 ]; then
        echo "Suche lokale Modelle ..."
        MODEL_DIRS=(
            "$HOME/.cache/lm-studio"
            "$HOME/.cache/LM-Studio"
            "$HOME/.lmstudio/models"
            "$HOME/LM Studio/models"
            "$SCRIPT_DIR/models"
        )
        MAPFILE_ARR=()
        for d in "${MODEL_DIRS[@]}"; do
            [ -d "$d" ] || continue
            while IFS= read -r f; do
                MAPFILE_ARR+=("$f")
            done < <(find "$d" -maxdepth 6 -type f \( -iname "*.gguf" -o -iname "*.bin" -o -iname "*.safetensors" \) 2>/dev/null)
        done

        if [ ${#MAPFILE_ARR[@]} -eq 0 ]; then
            echo "Keine lokalen Modelle gefunden." >&2
            while true; do
                cd_pid=$(countdown_prompt "$SELECT_TIMEOUT" "[S]kip ohne Modell, [Q]uit beenden:")
                if read -r -t "$SELECT_TIMEOUT" ans < /dev/tty; then
                    kill "$cd_pid" 2>/dev/null || true; wait "$cd_pid" 2>/dev/null || true; echo; echo >&2
                    if [ "$DEBUG_FLAG" = "1" ] || [ "${LM_AUTOSTART_DEBUG:-0}" = "1" ]; then
                        echo "[DEBUG] Eingabe erkannt (no-models): '$ans'"
                    fi
                else
                    kill "$cd_pid" 2>/dev/null || true; wait "$cd_pid" 2>/dev/null || true; echo; echo >&2
                    ans="s"
                    echo "Automatische Auswahl: Skip (Timeout ${SELECT_TIMEOUT}s)."
                fi
                case "${ans,,}" in
                    s|skip)
                        echo "Kein Modell wird geladen."
                        break ;;
                    q|quit)
                        echo "Beendet."; exit 0 ;;
                    *)
                        echo "Ungültige Eingabe." ;;
                esac
            done
        else
            echo "Gefundene Modelle:";
            i=1
            for f in "${MAPFILE_ARR[@]}"; do
                echo "  $i) $(basename "$f")"; i=$((i+1))
            done
            echo "  s) Skip (kein Modell laden)"
            echo "  q) Quit (Skript beenden)"

            attempts=0
            while true; do
                cd_pid=$(countdown_prompt "$SELECT_TIMEOUT" "Auswahl [1-${#MAPFILE_ARR[@]}|s|q]:")
                if read -r -t "$SELECT_TIMEOUT" pick < /dev/tty; then
                    kill "$cd_pid" 2>/dev/null || true; wait "$cd_pid" 2>/dev/null || true; echo; echo >&2
                    if [ "$DEBUG_FLAG" = "1" ] || [ "${LM_AUTOSTART_DEBUG:-0}" = "1" ]; then
                        echo "[DEBUG] Eingabe erkannt (models): '$pick'"
                    fi
                else
                    kill "$cd_pid" 2>/dev/null || true; wait "$cd_pid" 2>/dev/null || true; echo; echo >&2
                    pick="s"
                    echo "Automatische Auswahl: Skip (Timeout ${SELECT_TIMEOUT}s)."
                fi
                if [[ "${pick,,}" == "q" ]]; then echo "Beendet."; exit 0; fi
                if [[ "${pick,,}" == "s" ]]; then echo "Kein Modell wird geladen."; break; fi
                if [[ "$pick" =~ ^[0-9]+$ ]] && [ "$pick" -ge 1 ] && [ "$pick" -le ${#MAPFILE_ARR[@]} ]; then
                    CHOSEN="${MAPFILE_ARR[$((pick-1))]}"
                    echo "Ausgewählt: $CHOSEN"
                    if [ "$MODEL_EXPLICIT" -eq 0 ]; then
                        MODEL="$CHOSEN"
                        if [ "$DEBUG_FLAG" = "1" ] || [ "${LM_AUTOSTART_DEBUG:-0}" = "1" ]; then
                            base_name="$(basename "$CHOSEN")";
                            parent_dir="$(basename "$(dirname "$CHOSEN")")";
                            grand_dir="$(basename "$(dirname "$(dirname "$CHOSEN")")")";
                            echo "[DEBUG] Auswahl-Datei: $CHOSEN (id-Kandidat: $grand_dir/$parent_dir/$base_name)"
                        fi
                    else
                        echo "Hinweis: --model wurde bereits gesetzt und hat Vorrang; Auswahl wird ignoriert." >&2
                    fi
                    break
                fi
                echo "Ungültige Eingabe."; attempts=$((attempts+1));
                if [ $attempts -ge 5 ]; then
                    echo "Zu viele ungültige Eingaben. Weiter ohne Modellauswahl."
                    break
                fi
            done
        fi
    else
        list_models
        exit $?
    fi
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
LMS_CLI="$HOME/.lmstudio/bin/lms"
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

resolve_model_arg() {
    local input="$1"; local lmscmd="$2"
    if [ -f "$input" ] && [ -x "$lmscmd" ]; then
        local base
        base="$(basename "$input")"
        local out rc
        set +e
        out="$($lmscmd ls 2>/dev/null)"; rc=$?
        set -e
        if [ $rc -eq 0 ] && [ -n "$out" ]; then
            local line id
            line="$(printf '%s\n' "$out" | grep -F "$base" | head -n 1)"
            if [ -n "$line" ]; then
                id="$(printf '%s\n' "$line" | sed -E 's/[[:space:]]*\([^\)]*\)[[:space:]]*$//' | sed -E 's/^[[:space:]]+//' | awk '{print $1}')"
                if [ -n "$id" ]; then
                    printf '%s\n' "$id"; return 0
                fi
            fi
            local base_noext
            base_noext="${base%.gguf}"; base_noext="${base_noext%.bin}"; base_noext="${base_noext%.safetensors}"
            local match
            match="$(printf '%s\n' "$out" | awk '{print $1}' | grep -i "$base_noext" | head -n 1)"
            if [ -n "$match" ]; then
                printf '%s\n' "$match"; return 0
            fi
        fi
        printf '%s\n' "$input"; return 0
    fi
    printf '%s\n' "$input"
}

ensure_model_registered() {
    local path="$1"; local lmscmd="$2"
    [ -f "$path" ] || { printf '%s\n' "$path"; return 0; }
    local base out line id rc
    base="$(basename "$path")"
    set +e
    out="$($lmscmd ls 2>/dev/null)"; rc=$?
    set -e
    if [ $rc -eq 0 ] && [ -n "$out" ]; then
        line="$(printf '%s\n' "$out" | grep -F "$base" | head -n 1)"
        if [ -n "$line" ]; then
            id="$(printf '%s\n' "$line" | sed -E 's/[[:space:]]*\([^\)]*\)[[:space:]]*$//' | sed -E 's/^[[:space:]]+//' | awk '{print $1}')"
            if [ -n "$id" ]; then printf '%s\n' "$id"; return 0; fi
        fi
        local best_id="" best_score=0 candidate
        local tokens token base_lc
        base_lc="$(printf '%s' "$base" | tr '[:upper:]' '[:lower:]')"
        base_lc="${base_lc%.gguf}"; base_lc="${base_lc%.bin}"; base_lc="${base_lc%.safetensors}"
        base_lc="$(printf '%s' "$base_lc" | sed 's/[_.-]/ /g')"
        read -r -a tokens <<<"$base_lc"
        for candidate in $(printf '%s\n' "$out" | awk '{print $1}' | grep -E '^[A-Za-z0-9_./-]+$' | sed 's/\x1b\[[0-9;]*m//g'); do
            local cand_lc score=0 t
            cand_lc="$(printf '%s' "$candidate" | tr '[:upper:]' '[:lower:]')"
            for t in "${tokens[@]}"; do
                case "$t" in
                    "q4"|"q5"|"q6"|"q8"|"k"|"m"|"gguf"|"q4_k_m"|"q8_0"|"q4_0"|"q5_1"|"q2_k"|"q3_k") continue ;; # ignoriere häufige Quantisierungs-Tokens
                esac
                if [ -n "$t" ] && printf '%s' "$cand_lc" | grep -q "$t"; then
                    score=$((score+1))
                fi
            done
            if [ $score -gt $best_score ]; then
                best_score=$score; best_id="$candidate"
            fi
        done
        if [ -n "$best_id" ] && [ $best_score -ge 2 ]; then
            printf '%s\n' "$best_id"; return 0
        fi
    fi
    if [ "$DEBUG_FLAG" = "1" ] || [ "${LM_AUTOSTART_DEBUG:-0}" = "1" ]; then
        echo "[DEBUG] Importiere Modell-Datei in LM Studio: $path" >&2
    fi
    if printf 'y\n' | "$lmscmd" import --symbolic-link "$path" >/dev/null 2>&1; then
        sleep 1
        set +e
        out="$($lmscmd ls 2>/dev/null)"; rc=$?
        set -e
        if [ $rc -eq 0 ] && [ -n "$out" ]; then
            line="$(printf '%s\n' "$out" | grep -F "$base" | head -n 1)"
            if [ -n "$line" ]; then
                id="$(printf '%s\n' "$line" | sed -E 's/[[:space:]]*\([^\)]*\)[[:space:]]*$//' | sed -E 's/^[[:space:]]+//' | awk '{print $1}')"
                if [ -n "$id" ]; then printf '%s\n' "$id"; return 0; fi
            fi
            local base_noext2
            base_noext2="${base%.gguf}"; base_noext2="${base_noext2%.bin}"; base_noext2="${base_noext2%.safetensors}"
            local match2
            match2="$(printf '%s\n' "$out" | awk '{print $1}' | grep -i "$base_noext2" | head -n 1)"
            if [ -n "$match2" ]; then
                printf '%s\n' "$match2"; return 0
            fi
        fi
    else
        echo "[WARN] Import schlug fehl für: $path" >&2
    fi
    printf '%s\n' "$path"
}

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
    if have notify-send; then
        notify-send "LM Studio" "LM Studio wird gestartet..." -i dialog-information || true
    fi
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

# === API-Server-Warte-Logik: Warte bis HTTP-API erreichbar ist (stabil) ===
HTTP_CFG="$HOME/.lmstudio/.internal/http-server-config.json"
API_PORT=""
if [ -f "$HTTP_CFG" ]; then
    API_PORT=$(grep -oE '"port"\s*:\s*[0-9]+' "$HTTP_CFG" | grep -oE '[0-9]+' | head -n 1)
fi
API_PORT="${API_PORT:-1234}"
API_WAIT="${API_WAIT:-30}"
if have curl; then
    try_ports=("$API_PORT")
    if [ "$API_PORT" = "1234" ]; then
        try_ports+=("41343")
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') 🌐 Warte auf LM Studio API (Ports: ${try_ports[*]}, bis zu ${API_WAIT}s)..."
    successes=0
    waited=0
    active_port=""
    while [ "$waited" -lt "$API_WAIT" ]; do
        for p in "${try_ports[@]}"; do
            if curl -sS --max-time 1 "http://127.0.0.1:$p/" >/dev/null 2>&1; then
                active_port="$p"
                successes=$((successes+1))
                break
            fi
            successes=0
        done
        if [ "$successes" -ge 2 ]; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ API erreichbar auf Port $active_port."
            break
        fi
        sleep 1
        waited=$((waited+1))
        if [ -f "$HTTP_CFG" ]; then
            new_port=$(grep -oE '"port"\s*:\s*[0-9]+' "$HTTP_CFG" | grep -oE '[0-9]+' | head -n 1)
            if [ -n "$new_port" ] && [ "$new_port" != "$API_PORT" ]; then
                API_PORT="$new_port"
                try_ports=("$API_PORT")
                if [ "$API_PORT" = "1234" ]; then try_ports+=("41343"); fi
                echo "[DEBUG] Aktualisierte API-Port-Erkennung: $API_PORT"
            fi
        fi
    done
    if [ "$successes" -lt 2 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ API nicht stabil erreichbar – versuche trotzdem das Laden."
    fi
fi

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
        if ! "$LMS_CMD" ps </dev/null >/dev/null 2>&1; then
            sleep 1
            "$LMS_CMD" ps </dev/null >/dev/null 2>&1 || true
        fi
        ATTEMPT=1
        LOAD_OK=false
        if [ -f "$MODEL" ]; then
            RESOLVED_MODEL="$(ensure_model_registered "$MODEL" "$LMS_CMD")"
        else
            RESOLVED_MODEL="$(resolve_model_arg "$MODEL" "$LMS_CMD")"
        fi
        RESOLVED_MODEL="$(printf '%s' "$RESOLVED_MODEL" | head -n 1 | sed 's/^\s\+//; s/\s\+$//')"
        while [ "$ATTEMPT" -le "$LMS_RETRIES" ]; do
            echo "$(date '+%Y-%m-%d %H:%M:%S') ▶️ Lade-Versuch $ATTEMPT/$LMS_RETRIES: '$MODEL' mit GPU=$GPU"
            if "$LMS_CMD" load "$RESOLVED_MODEL" --gpu="$GPU" </dev/null; then
                LOAD_OK=true; break
            fi
            sleep "$LMS_RETRY_SLEEP"; ATTEMPT=$((ATTEMPT + 1))
        done

        if ! $LOAD_OK; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ Laden mit GPU=$GPU fehlgeschlagen – versuche CPU-Fallback (GPU=0.0)."
            if "$LMS_CMD" load "$RESOLVED_MODEL" --gpu="0.0" </dev/null; then
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
TRAY_MODEL="$MODEL"
if [ -n "$RESOLVED_MODEL" ] && [ "$RESOLVED_MODEL" != "$MODEL" ]; then
    TRAY_MODEL="$RESOLVED_MODEL"
fi
echo "$(date '+%Y-%m-%d %H:%M:%S') 🐍 Starte Tray-Monitor: $SCRIPT_DIR/lmstudio_tray.py mit Modell '$TRAY_MODEL'"
if have python3; then
    python3 "$SCRIPT_DIR/lmstudio_tray.py" "$TRAY_MODEL" "$SCRIPT_DIR" &
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ Tray nicht gestartet – python3 nicht gefunden."
fi

