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

# === Basic dependency checks ===
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
    if ! command -v llmster >/dev/null 2>&1 \
        && ! find "$HOME/.lmstudio/llmster" -maxdepth 3 -type f -name "llmster" -perm -111 2>/dev/null | grep -q .; then
        missing+=("llmster (headless daemon)")
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
        if ! command -v llmster >/dev/null 2>&1 \
            && ! find "$HOME/.lmstudio/llmster" -maxdepth 3 -type f -name "llmster" -perm -111 2>/dev/null | grep -q .; then
            echo "llmster (headless daemon) is missing." >&2
            echo "Install llmster and run this script again." >&2
            exit 1
        fi
    fi
}

check_dependencies

# === Help ===
usage() {
    cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Starts the Python tray monitor for LM Studio status control.
Default behavior (without --gui): starts llmster (headless daemon) and tray monitor.
With --gui: if llmster is running, it is stopped first; then LM Studio desktop app + tray monitor are started.
The log file is created anew per run in .logs directory: lmstudio_autostart.log

Options:
    -d, --debug       Enable debug output and Bash trace (also terminal output)
    -h, --help        Show this help and exit
    -L, --list-models List local models; in TTY: interactive selection with 30s auto-skip (no LM Studio start before selection)
    -g, --gui         Start the LM Studio desktop app and tray monitor

Environment variables:
    LM_AUTOSTART_DEBUG=1            Force debug mode (equivalent to --debug)
    LM_AUTOSTART_SELECT_TIMEOUT=30  Timeout (seconds) for interactive -L selection; after expiry, "Skip" is automatically selected
    LM_AUTOSTART_GUI_CMD="..."      Explicit command to launch the GUI

Exit codes:
    0  Success
    1  Setup failed
    2  Invalid option/usage
    3  No models found (-L mode)

Examples:
    $(basename "$0")         # Start llmster + tray monitor
    $(basename "$0") --debug # With debug output
    $(basename "$0") -L      # Interactive model selection (in TTY) or list (without TTY)
    $(basename "$0") --gui   # Stop llmster (if running), then start LM Studio desktop app + tray monitor
EOF
}

# === List local models (without starting LM Studio) ===
model_label_from_path() {
    local path="$1"
    local base parent grand
    base="$(basename "$path")"
    if [ "$base" = "manifest.json" ]; then
        parent="$(basename "$(dirname "$path")")"
        grand="$(basename "$(dirname "$(dirname "$path")")")"
        printf '%s/%s\n' "$grand" "$parent"
        return 0
    fi
    printf '%s\n' "$base"
}

list_models() {
    echo "Local models (without starting LM Studio):"
    local found=0

    local LMS_CANDIDATES=("$HOME/.lmstudio/bin/lms")
    if command -v lms >/dev/null 2>&1; then LMS_CANDIDATES+=("$(command -v lms)"); fi

    for cand in "${LMS_CANDIDATES[@]}"; do
        if [ -z "$cand" ] || [ ! -x "$cand" ]; then
            continue
        fi
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
        "$HOME/.lmstudio/hub/models"
        "$HOME/LM Studio/models"
        "$SCRIPT_DIR/models"
    )
    for dir in "${dirs[@]}"; do
        [ -d "$dir" ] || continue
        local -a files=()
        set +e
        mapfile -t files < <(find "$dir" -maxdepth 6 -type f \( -iname "*.gguf" -o -iname "*.bin" -o -iname "*.safetensors" -o -iname "manifest.json" \) 2>/dev/null)
        set -e
        if [ ${#files[@]} -gt 0 ]; then
            echo "Source: $dir"
            for f in "${files[@]}"; do
                echo " - $(model_label_from_path "$f")  [$f]"
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

# === Parse arguments ===
DEBUG_FLAG=0
LIST_MODELS=0
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
        --)
            shift; break ;;
        -*)
                        echo "Error: Unknown option: $1" >&2
                        usage >&2
            exit 2 ;;
        *)
            if [ "$DEBUG_FLAG" = "1" ] || [ "${LM_AUTOSTART_DEBUG:-0}" = "1" ]; then
                echo "Note: Positional argument '$1' is ignored." >&2
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
            "$HOME/.lmstudio/hub/models"
            "$HOME/LM Studio/models"
            "$SCRIPT_DIR/models"
        )
        MAPFILE_ARR=()
        for d in "${MODEL_DIRS[@]}"; do
            [ -d "$d" ] || continue
            while IFS= read -r f; do
                MAPFILE_ARR+=("$f")
            done < <(find "$d" -maxdepth 6 -type f \( -iname "*.gguf" -o -iname "*.bin" -o -iname "*.safetensors" -o -iname "manifest.json" \) 2>/dev/null)
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
                echo "  $i) $(model_label_from_path "$f")"; i=$((i+1))
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
                    CHOSEN_LABEL="$(model_label_from_path "$CHOSEN")"
                    echo "Selected: $CHOSEN_LABEL"
                    if [ "$DEBUG_FLAG" = "1" ] || [ "${LM_AUTOSTART_DEBUG:-0}" = "1" ]; then
                        echo "[DEBUG] Selected file: $CHOSEN (label: $CHOSEN_LABEL)"
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
{
    echo "================================================================================"
    echo "LM Studio Autostart Log"
    echo "Started: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "================================================================================"
} > "$LOGFILE"
if [ "$DEBUG_FLAG" = "1" ]; then
    # Debug mode: terminal + log file (with all traces)
    exec > >(tee -a "$LOGFILE") 2>&1
    set -x
    echo "[DEBUG] Terminal and log output enabled: $LOGFILE"
else
    # Normal mode: only log file
    exec >> "$LOGFILE" 2>&1
fi
LMS_CLI="$HOME/.lmstudio/bin/lms"

export LMSTUDIO_DISABLE_AUTO_LAUNCH=true

# === Command helpers ===
have() { command -v "$1" >/dev/null 2>&1; }

get_llmster_cmd() {
    if have llmster; then
        command -v llmster
        return 0
    fi
    local llmster_candidate
    llmster_candidate="$(find "$HOME/.lmstudio/llmster" -maxdepth 3 -type f -name "llmster" -perm -111 2>/dev/null | sort -V | tail -n 1)"
    if [ -n "$llmster_candidate" ]; then
        printf '%s\n' "$llmster_candidate"
        return 0
    fi
    return 1
}

is_llmster_running() {
    pgrep -f "(^|/)llmster( |$)" >/dev/null 2>&1
}

run_llmster_cmd_expect_state() {
    local expected_state="$1"
    shift

    timeout 8 "$@" >/dev/null 2>&1
    local rc=$?

    if [ $rc -eq 124 ]; then
        if [ "$expected_state" = "running" ] && is_llmster_running; then
            return 0
        fi
        if [ "$expected_state" = "stopped" ] && ! is_llmster_running; then
            return 0
        fi
    fi

    return "$rc"
}

start_llmster() {
    local cmd lms_cmd
    cmd="$(get_llmster_cmd || true)"
    lms_cmd="$(get_lms_cmd || true)"
    if [ -z "$cmd" ] && [ -z "$lms_cmd" ]; then
        return 1
    fi

    set +e
    # Prefer lms wrapper when available (usually non-blocking)
    if [ -n "$lms_cmd" ]; then
        run_llmster_cmd_expect_state running "$lms_cmd" daemon up
        rc=$?
        if [ $rc -eq 0 ]; then
            set -e
            return 0
        fi
    fi

    if [ -n "$cmd" ]; then
        rc=1
        run_llmster_cmd_expect_state running "$cmd" daemon start
        rc=$?
        if [ $rc -ne 0 ]; then
            run_llmster_cmd_expect_state running "$cmd" start
            rc=$?
        fi
        if [ $rc -ne 0 ]; then
            run_llmster_cmd_expect_state running "$cmd" daemon up
            rc=$?
        fi
        if [ $rc -ne 0 ]; then
            run_llmster_cmd_expect_state running "$cmd" up
            rc=$?
        fi
    else
        rc=1
    fi

    set -e
    return "$rc"
}

stop_llmster() {
    local cmd lms_cmd
    cmd="$(get_llmster_cmd || true)"
    lms_cmd="$(get_lms_cmd || true)"
    if [ -z "$cmd" ] && [ -z "$lms_cmd" ]; then
        return 0
    fi

    set +e
    # Prefer lms wrapper when available
    if [ -n "$lms_cmd" ]; then
        run_llmster_cmd_expect_state stopped "$lms_cmd" daemon down
        rc=$?
        if [ $rc -eq 0 ]; then
            set -e
            return 0
        fi
    fi

    if [ -n "$cmd" ]; then
        rc=1
        run_llmster_cmd_expect_state stopped "$cmd" daemon stop
        rc=$?
        if [ $rc -ne 0 ]; then
            run_llmster_cmd_expect_state stopped "$cmd" stop
            rc=$?
        fi
        if [ $rc -ne 0 ]; then
            run_llmster_cmd_expect_state stopped "$cmd" daemon down
            rc=$?
        fi
        if [ $rc -ne 0 ]; then
            run_llmster_cmd_expect_state stopped "$cmd" down
            rc=$?
        fi
    else
        rc=0
    fi

    # Fallback: ensure process is actually gone
    if is_llmster_running; then
        pkill -f "(^|/)llmster( |$)" >/dev/null 2>&1 || true
        sleep 1
    fi
    if is_llmster_running; then
        rc=1
    fi

    set -e
    return "$rc"
}

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
    stop_llmster
}

resolve_model_arg() {
    local input="$1"; local lmscmd="$2"
    if [ -f "$input" ] && [ -x "$lmscmd" ]; then
        local base
        base="$(basename "$input")"
        local out rc
        set +e
        out="$("$lmscmd" ls 2>/dev/null)"; rc=$?
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
    out="$("$lmscmd" ls 2>/dev/null)"; rc=$?
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
        out="$("$lmscmd" ls 2>/dev/null)"; rc=$?
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

load_model_into_daemon() {
    local model_input="$1"
    [ -n "$model_input" ] || return 0

    local lmscmd
    lmscmd="$(get_lms_cmd || true)"
    if [ -z "$lmscmd" ]; then
        echo "[WARN] Cannot load model '$model_input': lms CLI not found." >&2
        return 1
    fi

    local model_key
    model_key="$(resolve_model_arg "$model_input" "$lmscmd")"
    model_key="$(ensure_model_registered "$model_key" "$lmscmd")"

    if [ "$DEBUG_FLAG" = "1" ] || [ "${LM_AUTOSTART_DEBUG:-0}" = "1" ]; then
        echo "[DEBUG] Loading model into daemon: input='$model_input' key='$model_key'" >&2
    fi

    set +e
    "$lmscmd" load --yes --local "$model_key" >/dev/null 2>&1
    local rc=$?
    if [ $rc -ne 0 ]; then
        "$lmscmd" load --yes "$model_key" >/dev/null 2>&1
        rc=$?
    fi
    set -e

    if [ $rc -eq 0 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ Model loaded: $model_key"
        return 0
    fi

    echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ Model load failed: $model_key" >&2
    return 1
}

if [ "$GUI_FLAG" -eq 1 ]; then
    # GUI mode: start desktop app + tray monitor
    if is_llmster_running; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') 🛑 llmster is running - stopping before GUI start..."
        stop_llmster || true
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') ℹ️ llmster not running - continuing with GUI start..."
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') 🖥️ Starting LM Studio GUI..."
    start_gui || true
    TRAY_MODEL="no-model"
else
    # Default mode: start llmster headless daemon + tray
    echo "$(date '+%Y-%m-%d %H:%M:%S') 🚀 Starting llmster headless daemon..."
    if start_llmster; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ llmster started."
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') ❌ Failed to start llmster." >&2
        if have notify-send; then
            notify-send "LLMster" "Failed to start llmster headless daemon" -i dialog-error || true
        fi
    fi
    echo "$(date '+%Y-%m-%d %H:%M:%S') ℹ️ Use --gui to stop llmster and start LM Studio desktop app."

    TRAY_MODEL="no-model"
fi

# Pass debug flag to tray script if enabled
if [ "$DEBUG_FLAG" = "1" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') 🐛 Debug mode enabled for tray monitor"
fi

TRAY_BIN=""
if [ -x "$SCRIPT_DIR/lmstudio-tray-manager" ]; then
    TRAY_BIN="$SCRIPT_DIR/lmstudio-tray-manager"
elif [ -x "$SCRIPT_DIR/dist/lmstudio-tray-manager" ]; then
    TRAY_BIN="$SCRIPT_DIR/dist/lmstudio-tray-manager"
fi

TRAY_ARGS=("$TRAY_MODEL" "$SCRIPT_DIR")
if [ "$DEBUG_FLAG" = "1" ]; then
    TRAY_ARGS+=("--debug")
fi
if [ "$GUI_FLAG" -eq 1 ]; then
    TRAY_ARGS+=("--gui")
else
    TRAY_ARGS+=("--auto-start-daemon")
fi

if [ -n "$TRAY_BIN" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') 🧩 Tray launch mode: binary"
    echo "$(date '+%Y-%m-%d %H:%M:%S') 🧩 Starting Tray-Monitor (binary): $TRAY_BIN"
    "$TRAY_BIN" "${TRAY_ARGS[@]}" &
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') 🐍 Tray launch mode: python"
    echo "$(date '+%Y-%m-%d %H:%M:%S') 🐍 Starting Tray-Monitor: \
$SCRIPT_DIR/lmstudio_tray.py with model '$TRAY_MODEL'"
    # Priority: venv > python3.10 > python3 (PyGObject compatibility)
    if [ -x "$VENV_DIR/bin/python3" ]; then
        "$VENV_DIR/bin/python3" "$SCRIPT_DIR/lmstudio_tray.py" \
            "${TRAY_ARGS[@]}" &
    elif have python3.10; then
        python3.10 "$SCRIPT_DIR/lmstudio_tray.py" \
            "${TRAY_ARGS[@]}" &
    elif have python3; then
        python3 "$SCRIPT_DIR/lmstudio_tray.py" \
            "${TRAY_ARGS[@]}" &
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️ Tray not started - no Python interpreter found."
    fi
fi

