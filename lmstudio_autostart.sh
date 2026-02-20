#!/usr/bin/env bash
set -e

# === Settings ===
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="${VENV_DIR:-$SCRIPT_DIR/venv}"
LOGS_DIR="$SCRIPT_DIR/.logs"

# === Create logs directory if not exists ===
mkdir -p "$LOGS_DIR"

# === Log file in .logs directory ===
LOGFILE="$LOGS_DIR/lmstudio_autostart.log"

# === Check dependencies ===
check_dependencies() {
    local missing=()
    local to_install=()

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
    if ! command -v lms >/dev/null 2>&1 && [ ! -x "$HOME/.lmstudio/bin/lms" ]; then
        missing+=("lms (LM Studio daemon CLI)")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        echo "The following dependencies are missing: ${missing[*]}"
        if [ ${#to_install[@]} -gt 0 ]; then
            echo "Do you want to install the apt-based dependencies now? (Y/n) [Y]"
            read -r answer
            answer=${answer:-Y}
            if [[ "$answer" =~ ^[yYnN] ]]; then
                for cmd in "${to_install[@]}"; do
                    echo "Running: $cmd"
                    eval "$cmd"
                done
            else
                echo "Dependencies are required. Exiting."
                exit 1
            fi
        fi
        if ! command -v lms >/dev/null 2>&1 && [ ! -x "$HOME/.lmstudio/bin/lms" ]; then
            echo "LM Studio daemon CLI (lms) is missing. Install LM Studio for Linux:" >&2
            echo "  https://lmstudio.ai/" >&2
            exit 1
        fi
    fi
}

check_dependencies

# === Help ===
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Starts the LM Studio daemon, checks and installs dependencies (curl, notify-send, python3),
optionally loads a model via lms-CLI with GPU fallback and starts the tray monitor with status monitoring.
The log file is created anew per run in .logs directory: lmstudio_autostart.log

Options:
    -d, --debug       Enable debug output and Bash trace (also terminal output)
    -h, --help        Show this help and exit
    -L, --list-models List local models; in TTY: interactive selection with 30s auto-skip (no LM Studio start before selection)
    -m, --model NAME  Load specified model (if NAME is missing, no model is loaded)
    -g, --gui         Start the LM Studio GUI (stops daemon first)

Environment variables:
    LM_AUTOSTART_DEBUG=1            Force debug mode (equivalent to --debug)
    LM_AUTOSTART_SELECT_TIMEOUT=30  Timeout (seconds) for interactive -L selection; after expiry, "Skip" is automatically selected
    LM_AUTOSTART_GUI_CMD="..."      Explicit command to launch the GUI

Exit codes:
    0  Success
    1  Daemon not available or setup failed
    2  Invalid option/usage
    3  No models found (-L mode)

Examples:
    $(basename "$0")                             # Normal start with setup/dependency check
    $(basename "$0") --debug                     # With debug output
    $(basename "$0") --model qwen2.5:7b-instruct # Load model
    $(basename "$0") -m qwen2.5:7b-instruct      # Short form
    $(basename "$0") -m                          # Flag without name: loads no model
    $(basename "$0") -L                          # Interactive model selection (in TTY) or list (without TTY)
    $(basename "$0") --gui                       # Start the GUI in addition to the daemon
EOF
}

# === List local models (without starting LM Studio) ===
list_models() {
    echo "Local models (without starting LM Studio):"
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
            echo "Source: lms ($cand)"
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
            echo "Source: $dir"
            for f in "${files[@]}"; do
                echo " - $(basename "$f")  [$f]"
            done
            found=1
        fi
    done

    if [ "$found" -eq 0 ]; then
        echo "No local models found."
        return 3
    fi
    return 0
}

# === Parse arguments (Debug flag, Model name) ===
DEBUG_FLAG=0
MODEL=""
LIST_MODELS=0
MODEL_EXPLICIT=0
GUI_FLAG=0
SELECT_TIMEOUT="${LM_AUTOSTART_SELECT_TIMEOUT:-30}"
while [ $# -gt 0 ]; do
    case "$1" in
        --debug|-d)
            DEBUG_FLAG=1; shift ;;
                --help|-h)
                        usage; exit 0 ;;
        --list-models|-L)
            LIST_MODELS=1; shift ;;
        --gui|-g)
            GUI_FLAG=1; shift ;;
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
                        echo "Error: Unknown option: $1" >&2
                        usage >&2
            exit 2 ;;
        *)
            if [ "$DEBUG_FLAG" = "1" ] || [ "${LM_AUTOSTART_DEBUG:-0}" = "1" ]; then
                echo "Note: Positional argument '$1' is ignored. Please use --model/-m NAME." >&2
            fi
            shift ;;
    esac
done

countdown_prompt() {
    local timeout="$1"; shift
    local prompt="$*"
    local t
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
        echo "Searching for local models ..."
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
            echo "No local models found." >&2
            while true; do
                cd_pid=$(countdown_prompt "$SELECT_TIMEOUT" "[S]kip without model, [Q]uit exit:")
                if read -r -t "$SELECT_TIMEOUT" ans < /dev/tty; then
                    kill "$cd_pid" 2>/dev/null || true; wait "$cd_pid" 2>/dev/null || true; echo; echo >&2
                    if [ "$DEBUG_FLAG" = "1" ] || [ "${LM_AUTOSTART_DEBUG:-0}" = "1" ]; then
                        echo "[DEBUG] Input detected (no-models): '$ans'"
                    fi
                else
                    kill "$cd_pid" 2>/dev/null || true; wait "$cd_pid" 2>/dev/null || true; echo; echo >&2
                    ans="s"
                    echo "Automatic selection: Skip (Timeout ${SELECT_TIMEOUT}s)."
                fi
                case "${ans,,}" in
                    s|skip)
                        echo "No model will be loaded."
                        break ;;
                    q|quit)
                        echo "Exited."; exit 0 ;;
                    *)
                        echo "Invalid input." ;;
                esac
            done
        else
            echo "Found models:";
            i=1
            for f in "${MAPFILE_ARR[@]}"; do
                echo "  $i) $(basename "$f")"; i=$((i+1))
            done
            echo "  s) Skip (do not load model)"
            echo "  q) Quit (terminate script)"

            attempts=0
            while true; do
                cd_pid=$(countdown_prompt "$SELECT_TIMEOUT" "Selection [1-${#MAPFILE_ARR[@]}|s|q]:")
                if read -r -t "$SELECT_TIMEOUT" pick < /dev/tty; then
                    kill "$cd_pid" 2>/dev/null || true; wait "$cd_pid" 2>/dev/null || true; echo; echo >&2
                    if [ "$DEBUG_FLAG" = "1" ] || [ "${LM_AUTOSTART_DEBUG:-0}" = "1" ]; then
                        echo "[DEBUG] Input detected (models): '$pick'"
                    fi
                else
                    kill "$cd_pid" 2>/dev/null || true; wait "$cd_pid" 2>/dev/null || true; echo; echo >&2
                    pick="s"
                    echo "Automatic selection: Skip (Timeout ${SELECT_TIMEOUT}s)."
                fi
                if [[ "${pick,,}" == "q" ]]; then echo "Exited."; exit 0; fi
                if [[ "${pick,,}" == "s" ]]; then echo "No model will be loaded."; break; fi
                if [[ "$pick" =~ ^[0-9]+$ ]] && [ "$pick" -ge 1 ] && [ "$pick" -le ${#MAPFILE_ARR[@]} ]; then
                    CHOSEN="${MAPFILE_ARR[$((pick-1))]}"
                    echo "Selected: $CHOSEN"
                    if [ "$MODEL_EXPLICIT" -eq 0 ]; then
                        MODEL="$CHOSEN"
                        if [ "$DEBUG_FLAG" = "1" ] || [ "${LM_AUTOSTART_DEBUG:-0}" = "1" ]; then
                            base_name="$(basename "$CHOSEN")";
                            parent_dir="$(basename "$(dirname "$CHOSEN")")";
                            grand_dir="$(basename "$(dirname "$(dirname "$CHOSEN")")")";
                            echo "[DEBUG] Selected file: $CHOSEN (id candidate: $grand_dir/$parent_dir/$base_name)"
                        fi
                    else
                        echo "Note: --model was already set and takes precedence; selection is ignored." >&2
                    fi
                    break
                fi
                echo "Invalid input."; attempts=$((attempts+1));
                if [ $attempts -ge 5 ]; then
                    echo "Too many invalid inputs. Continuing without model selection."
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

# === Logging configuration ===
     : > "$LOGFILE"
if [ "$DEBUG_FLAG" = "1" ]; then
    exec > >(tee -a >(sed 's/\x1b\[[0-9;]*m//g' >> "$LOGFILE")) \
         2> >(tee -a >(sed 's/\x1b\[[0-9;]*m//g' >> "$LOGFILE") >&2)
    set -x
    echo "[DEBUG] Terminal and log output enabled. Log: $LOGFILE"
else
    exec > >(sed 's/\x1b\[[0-9;]*m//g' >> "$LOGFILE") 2>&1
fi
LMS_CLI="$HOME/.lmstudio/bin/lms"
GPU="1.0"
LMS_RETRIES=3
LMS_RETRY_SLEEP=5

# === Model name (if not set via args, it remains empty) ===

export LMSTUDIO_DISABLE_AUTO_LAUNCH=true

# === Check dependencies (interactive suggestions) ===
have() { command -v "$1" >/dev/null 2>&1; }
get_lms_cmd() {
    if [ -x "$LMS_CLI" ]; then
        printf '%s\n' "$LMS_CLI"
        return 0
    fi
    if have lms; then
        command -v lms
        return 0
    fi
    return 1
}

start_gui() {
    local desktop_id
    if [ -n "${LM_AUTOSTART_GUI_CMD:-}" ]; then
        IFS=' ' read -r -a gui_cmd <<<"$LM_AUTOSTART_GUI_CMD"
        if [ ${#gui_cmd[@]} -gt 0 ]; then
            "${gui_cmd[@]}" >/dev/null 2>&1 &
            return 0
        fi
    fi
    if have lmstudio; then
        lmstudio >/dev/null 2>&1 &
        return 0
    fi
    if have lm-studio; then
        lm-studio >/dev/null 2>&1 &
        return 0
    fi
    if have gtk-launch; then
        for desktop_id in lmstudio lm-studio; do
            gtk-launch "$desktop_id" >/dev/null 2>&1 &
            return 0
        done
    fi
    if have xdg-open; then
        xdg-open "lmstudio://" >/dev/null 2>&1 &
        return 0
    fi
    echo "⚠️ GUI start failed. Set LM_AUTOSTART_GUI_CMD to a valid command." >&2
    return 1
}

stop_daemon() {
    local lms_cmd
    lms_cmd="$(get_lms_cmd || true)"
    if [ -z "$lms_cmd" ]; then
        return 0
    fi
    set +e
    "$lms_cmd" daemon down >/dev/null 2>&1
    if [ $? -ne 0 ]; then
        "$lms_cmd" daemon stop >/dev/null 2>&1
    fi
    set -e
}

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
        local tokens base_lc
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
        echo "[DEBUG] Importing model file into LM Studio: $path" >&2
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
        echo "[WARN] Import failed for: $path" >&2
    fi
    printf '%s\n' "$path"
}

if [ "$GUI_FLAG" -eq 1 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') 🛑 Stopping LM Studio daemon before GUI..."
    stop_daemon || true
    echo "$(date '+%Y-%m-%d %H:%M:%S') 🖥️ Starting LM Studio GUI..."
    start_gui || true
    exit 0
fi

LMS_CMD="$(get_lms_cmd || true)"
if [ -z "$LMS_CMD" ]; then
    echo "❌ lms CLI not found. Please install LM Studio." >&2
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') 🚀 Starting LM Studio daemon..."
set +e
"$LMS_CMD" daemon up
DAEMON_RC=$?
set -e
if [ $DAEMON_RC -ne 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') ❌ Failed to start LM Studio daemon (exit $DAEMON_RC)." >&2
    exit 1
fi

if have notify-send; then
    notify-send "LM Studio" "LM Studio daemon is running" -i dialog-information || true
fi

# === API server wait logic: wait until the HTTP API is reachable (stable) ===
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
    echo "$(date '+%Y-%m-%d %H:%M:%S') 🌐 Waiting for LM Studio API (Ports: ${try_ports[*]}, up to ${API_WAIT}s)..."
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
            echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ API reachable on port $active_port."
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
                echo "[DEBUG] Updated API port detection: $API_PORT"
            fi
        fi
    done
    if [ "$successes" -lt 2 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ API not stably reachable – attempting loading anyway."
    fi
fi

# === Load model if provided ===
if [ -n "$MODEL" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') 📦 Loading model: $MODEL ..."
    if [ -n "$LMS_CMD" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') 🔧 Using lms-CLI: $LMS_CMD"
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
            echo "$(date '+%Y-%m-%d %H:%M:%S') ▶️ Load attempt $ATTEMPT/$LMS_RETRIES: '$MODEL' with GPU=$GPU"
            if "$LMS_CMD" load "$RESOLVED_MODEL" --gpu="$GPU" </dev/null; then
                LOAD_OK=true; break
            fi
            sleep "$LMS_RETRY_SLEEP"; ATTEMPT=$((ATTEMPT + 1))
        done

        if ! $LOAD_OK; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ Loading with GPU=$GPU failed – trying CPU fallback (GPU=0.0)."
            if "$LMS_CMD" load "$RESOLVED_MODEL" --gpu="0.0" </dev/null; then
                LOAD_OK=true; GPU="0.0"
            fi
        fi

        if $LOAD_OK; then
            echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ Model loaded (GPU=$GPU)!"
            if have notify-send; then
                notify-send -i dialog-information -t 5000 "LM Studio" "✅ Model '$MODEL' loaded successfully! (GPU=$GPU)" || true
            fi
        else
            echo "$(date '+%Y-%m-%d %H:%M:%S') ❌ Model '$MODEL' could not be loaded – skipping."
            MODEL="failed-model"
        fi
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') ❌ lms-CLI not found – skipping loading."
        MODEL="failed-model"
    fi
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') ℹ️ No model provided – skipping loading."
    MODEL="no-model"
fi

# === Start tray monitor with model name (also placeholder) ===
TRAY_MODEL="$MODEL"
if [ -n "$RESOLVED_MODEL" ] && [ "$RESOLVED_MODEL" != "$MODEL" ]; then
    TRAY_MODEL="$RESOLVED_MODEL"
fi
echo "$(date '+%Y-%m-%d %H:%M:%S') 🐍 Starting Tray-Monitor: $SCRIPT_DIR/lmstudio_tray.py with model '$TRAY_MODEL'"
# Priority: venv > python3.10 > python3 (PyGObject compatibility)
if [ -x "$VENV_DIR/bin/python3" ]; then
    "$VENV_DIR/bin/python3" "$SCRIPT_DIR/lmstudio_tray.py" "$TRAY_MODEL" "$SCRIPT_DIR" &
elif have python3.10; then
    python3.10 "$SCRIPT_DIR/lmstudio_tray.py" "$TRAY_MODEL" "$SCRIPT_DIR" &
elif have python3; then
    python3 "$SCRIPT_DIR/lmstudio_tray.py" "$TRAY_MODEL" "$SCRIPT_DIR" &
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ Tray not started – no Python interpreter found."
fi

