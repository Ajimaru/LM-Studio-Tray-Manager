#!/usr/bin/env bash
# Setup script for LM-Studio-Tray-Manager
# Checks for LM Studio daemon, desktop app, and sets up Python venv
# Linux only

set -e

DRY_RUN=0

usage() {
    cat <<EOF
Usage: ./setup.sh [OPTIONS]

Options:
  -n, --dry-run   Show what would be done without changing system state
  -h, --help      Show this help and exit
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        -n|--dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" || exit 1; pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
LOGS_DIR="$SCRIPT_DIR/.logs"
LOGFILE="$LOGS_DIR/setup.log"
mkdir -p "$LOGS_DIR"
cat > "$LOGFILE" << EOF
================================================================================
LM Studio Setup Log
Started: $(date '+%Y-%m-%d %H:%M:%S')
================================================================================
EOF

log_output() {
    local level="$1"
    shift
    local message="$*"
    if [ -n "$HOME" ]; then
        message="${message//$HOME/~}"
    fi
    local log_entry
    log_entry="[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $message"
    echo "$log_entry" >> "$LOGFILE"
}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    local header="═══════════════════════════════════════"
    printf '%b\n' "${BLUE}${header}${NC}"
    printf '%b\n' "${BLUE}$1${NC}"
    printf '%b\n' "${BLUE}${header}${NC}"
    log_output "INFO" "--- $1 ---"
}

print_step() {
    printf '%b %s\n' "${GREEN}✓${NC}" "$1"
    log_output "OK" "$1"
}

print_error() {
    printf '%b %s\n' "${RED}✗${NC}" "$1"
    log_output "ERROR" "$1"
}

print_warning() {
    printf '%b %s\n' "${YELLOW}⚠${NC}" "$1"
    log_output "WARN" "$1"
}

print_info() {
    echo "$1"
    log_output "INFO" "$1"
}

ask_yes_no() {
    local prompt="$1"
    local response
    while true; do
        read -rp "$(printf '%b' "${YELLOW}${prompt}${NC} [y/n]: ")" response
        case "$response" in
            [yY][eE][sS]|[yY])
                return 0
                ;;
            [nN][oO]|[nN])
                return 1
                ;;
            *)
                printf '%b
' "Please answer y or n"
                ;;
        esac
    done
}

if [[ "$OSTYPE" != "linux"* ]]; then
    print_error "This script only works on Linux"
    exit 1
fi

print_header "LM-Studio-Tray-Manager Setup"
log_output "INFO" "Script directory: $SCRIPT_DIR"
log_output "INFO" "Log file: $LOGFILE"
log_output "INFO" "OS Type: $OSTYPE"
log_output "INFO" "Current user: $(whoami)"
log_output "INFO" "Shell: $SHELL"

if [ "$DRY_RUN" = "1" ]; then
    print_info "Dry-run mode enabled. No system changes will be made."
fi

# ============================================================================
# 1. Check LM Studio Daemon (Headless)
# ============================================================================
echo -e "\n${BLUE}Step 1: Checking LM Studio Daemon Installation${NC}"
log_output "INFO" "Step 1: Checking for LM Studio daemon"

if command -v lms >/dev/null 2>&1 || [ -x "$HOME/.lmstudio/bin/lms" ]; then
    print_step "LM Studio daemon found"
    LMS_CLI=$(command -v lms 2>/dev/null || echo "$HOME/.lmstudio/bin/lms")
    echo "   Location: $LMS_CLI"
    log_output "INFO" "LM Studio daemon found at: $LMS_CLI"
    if lms_version=$("$LMS_CLI" --version 2>&1); then
        log_output "INFO" "LM Studio daemon version: $lms_version"
    fi
else
    print_warning "LM Studio daemon not found"
    log_output "WARN" "LM Studio daemon (lms) not found in PATH or ~/.lmstudio/bin/"
    echo ""
    print_info "The LM Studio daemon (llmster) is required for the automation scripts."
    print_info "You can download it from: https://lmstudio.ai/"
    echo ""
    if [ "$DRY_RUN" = "1" ]; then
        print_info "[DRY-RUN] Would prompt for daemon download and open https://lmstudio.ai/"
        print_warning "Daemon is missing; real setup would stop here until installed"
        log_output "INFO" "DRY-RUN: Would prompt user to download LM Studio daemon"
    else
        if ask_yes_no "Would you like to download LM Studio daemon?"; then
            log_output "INFO" "User chose to download LM Studio daemon"
            print_info "Opening LM Studio download page..."
            if command -v xdg-open >/dev/null 2>&1; then
                log_output "INFO" "Opening download page with xdg-open"
                xdg-open "https://lmstudio.ai/" &
            elif command -v firefox >/dev/null 2>&1; then
                log_output "INFO" "Opening download page with firefox"
                firefox "https://lmstudio.ai/" &
            else
                log_output "INFO" "No browser launcher found, displaying URL"
                print_info "Please visit: https://lmstudio.ai/"
            fi
            print_error "Please install LM Studio daemon and run this script again"
            log_output "ERROR" "Setup cancelled - LM Studio daemon not installed"
            exit 1
        else
            log_output "ERROR" "User declined to download LM Studio daemon - setup cancelled"
            print_error "LM Studio daemon is required. Setup cancelled."
            exit 1
        fi
    fi
fi

# ============================================================================
# 2. Check LM Studio Desktop App
# ============================================================================
echo -e "\n${BLUE}Step 2: Checking LM Studio Desktop App${NC}"
log_output "INFO" "Step 2: Checking for LM Studio desktop app"

FOUND_DEB=false
APP_INSTALLED=false

if dpkg -l | grep -q lm-studio; then
    print_step "LM Studio desktop app found (deb package)"
    log_output "INFO" "LM Studio desktop app installed via deb package"
    APP_INSTALLED=true
    FOUND_DEB=true
fi

log_output "DEBUG" "Searching for AppImage in common locations"
for appimage_path in "$SCRIPT_DIR" "$HOME/LM_Studio" "$HOME/Applications" "$HOME/.local/bin" "$HOME/Apps" "/opt/lm-studio"; do
    if [ -d "$appimage_path" ]; then
        for appimage_file in "$appimage_path"/*.AppImage "$appimage_path"/LM-Studio* "$appimage_path"/LM\ Studio*; do
            if [ -f "$appimage_file" ]; then
                print_step "LM Studio desktop app found (AppImage)"
                log_output "INFO" "LM Studio desktop app found (AppImage) at: $appimage_file"
                APP_INSTALLED=true
                APPIMAGE_PATH="$appimage_path"
                break 2
            fi
        done
    fi
done

if [ "$APP_INSTALLED" = false ]; then
    print_warning "LM Studio desktop app not found"
    log_output "WARN" "LM Studio desktop app not found (checked deb package and AppImage locations)"
    echo ""
    print_info "The desktop app is required for the --gui option."
    print_info "Choose installation method:"
    print_info "  1) Install .deb package (recommended for Ubuntu/Debian)"
    print_info "  2) Use AppImage (manual download)"
    print_info "  3) Skip (can be installed later)"
    echo ""
    if [ "$DRY_RUN" = "1" ]; then
        print_info "[DRY-RUN] Would prompt for desktop app installation method"
        print_warning "Desktop app missing; --gui option would not work until installed"
        log_output "INFO" "DRY-RUN: Would prompt user for desktop app installation method"
        app_choice=3
    else
        read -p "Choose option [1-3]: " -r app_choice
        log_output "INFO" "User selected desktop app installation option: $app_choice"
    fi

    case "$app_choice" in
        1)
            log_output "INFO" "User chose deb package installation"
            echo "Opening LM Studio download page..."
            if [ "$DRY_RUN" = "1" ]; then
                print_info "[DRY-RUN] Would open https://lmstudio.ai/download"
            elif command -v xdg-open >/dev/null 2>&1; then
                log_output "INFO" "Opening download page with xdg-open"
                xdg-open "https://lmstudio.ai/download" &
            elif command -v firefox >/dev/null 2>&1; then
                log_output "INFO" "Opening download page with firefox"
                firefox "https://lmstudio.ai/download" &
            else
                log_output "INFO" "No browser launcher found, displaying URL"
                echo "Please visit: https://lmstudio.ai/download"
            fi
            print_warning "Please download and install the .deb package, then run this script again"
            log_output "WARN" "Setup paused - waiting for deb package installation"
            ;;
        2)
            log_output "INFO" "User chose AppImage installation"
            print_info "Enter path to AppImage file (or directory containing it): "
            read -r appimage_input
            log_output "INFO" "User provided AppImage path: $appimage_input"
            if [ -f "$appimage_input" ]; then
                APPIMAGE_PATH="$appimage_input"
                print_step "AppImage path set to: $APPIMAGE_PATH"
                log_output "INFO" "AppImage file validated: $APPIMAGE_PATH"
                APP_INSTALLED=true
            elif [ -d "$appimage_input" ]; then
                APPIMAGE_PATH="$appimage_input"
                print_step "AppImage directory set to: $APPIMAGE_PATH"
                log_output "INFO" "AppImage directory validated: $APPIMAGE_PATH"
                APP_INSTALLED=true
            else
                print_error "Invalid path: $appimage_input"
                log_output "ERROR" "Invalid AppImage path provided: $appimage_input"
            fi
            ;;
        3)
            log_output "INFO" "Desktop app installation skipped by user"
            print_warning "Desktop app installation skipped. The --gui option won't work until you install it."
            ;;
        *)
            log_output "ERROR" "Invalid desktop app installation option: $app_choice"
            print_error "Invalid option"
            ;;
    esac
fi

if [ "$APP_INSTALLED" = true ]; then
    if [ "$FOUND_DEB" = true ]; then
        echo "   Desktop app: deb package"
        log_output "INFO" "Desktop app installation method: deb package"
    elif [ -n "$APPIMAGE_PATH" ]; then
        echo "   Desktop app: AppImage at $APPIMAGE_PATH"
        log_output "INFO" "Desktop app installation method: AppImage at $APPIMAGE_PATH"
    fi
fi

# ============================================================================
# 3. Check if using binary release (skip venv creation if binary exists)
# ============================================================================
echo -e "\n${BLUE}Step 3: Checking Installation Type${NC}"
log_output "INFO" "Step 3: Detecting binary vs source installation"

BINARY_RELEASE=false
APPIMAGE_RELEASE=false
APPIMAGE_FILE=""

# Check for tray manager AppImage first (self-contained, bundles GTK3)
_appimg_count=0
for _appimg_cand in "$SCRIPT_DIR"/lmstudio-tray-manager*.AppImage; do
    if [ -f "$_appimg_cand" ]; then
        _appimg_count=$((_appimg_count + 1))
        if [ -z "$APPIMAGE_FILE" ]; then
            APPIMAGE_FILE="$_appimg_cand"
        fi
    fi
done
if [ "$_appimg_count" -gt 1 ]; then
    print_warning \
        "Multiple AppImage files found; using: $(basename "$APPIMAGE_FILE")"
    log_output "WARN" \
        "Multiple AppImages found in script dir; using first: $APPIMAGE_FILE"
fi

if [ -n "$APPIMAGE_FILE" ]; then
    if [ -x "$APPIMAGE_FILE" ]; then
        print_step "AppImage release detected ($(basename "$APPIMAGE_FILE"))"
        log_output "INFO" \
            "AppImage release detected: $(basename "$APPIMAGE_FILE")"
        print_info "Skipping Python virtual environment creation"
        APPIMAGE_RELEASE=true
        BINARY_RELEASE=true
    else
        print_warning \
            "Found AppImage but it is not executable: $(basename "$APPIMAGE_FILE")"
        log_output "WARN" \
            "AppImage lacks execute permission: $APPIMAGE_FILE"
        if [ "$DRY_RUN" = "1" ]; then
            print_info \
                "[DRY-RUN] Would make it executable: chmod +x $(basename "$APPIMAGE_FILE")"
            print_info "[DRY-RUN] Would treat this as an AppImage release after chmod"
            log_output "INFO" "DRY-RUN: Would chmod +x and treat as AppImage release"
            APPIMAGE_RELEASE=true
            BINARY_RELEASE=true
        else
            _appimg_name="$(basename "$APPIMAGE_FILE")"
            if ask_yes_no \
                "Make $_appimg_name executable (chmod +x) and continue as AppImage release?"; then
                log_output "INFO" "User accepted to make AppImage executable"
                if chmod +x "$APPIMAGE_FILE"; then
                    print_step "AppImage made executable"
                    log_output "INFO" \
                        "Successfully made AppImage executable: $APPIMAGE_FILE"
                    APPIMAGE_RELEASE=true
                    BINARY_RELEASE=true
                else
                    print_error "Failed to chmod +x $_appimg_name"
                    log_output "ERROR" "Failed to chmod +x $APPIMAGE_FILE"
                    exit 1
                fi
            else
                log_output "ERROR" \
                    "User declined to make AppImage executable - cannot continue"
                print_error \
                    "AppImage exists but is not executable; cannot continue safely. Setup cancelled."
                print_info "Fix permissions and re-run: chmod +x ./$_appimg_name"
                exit 1
            fi
        fi
    fi
elif [ -x "$SCRIPT_DIR/lmstudio-tray-manager" ]; then
    print_step "Binary release detected (lmstudio-tray-manager)"
    log_output "INFO" \
        "Binary release detected: executable lmstudio-tray-manager found"
    print_info "Skipping Python virtual environment creation"
    BINARY_RELEASE=true
elif [ -f "$SCRIPT_DIR/lmstudio-tray-manager" ]; then
    print_warning "Found lmstudio-tray-manager but it is not executable"
    log_output "WARN" \
        "Binary file exists but lacks execute permission: $SCRIPT_DIR/lmstudio-tray-manager"
    if [ "$DRY_RUN" = "1" ]; then
        print_info \
            "[DRY-RUN] Would make it executable: chmod +x $SCRIPT_DIR/lmstudio-tray-manager"
        print_info "[DRY-RUN] Would treat this as a binary release after chmod"
        log_output "INFO" "DRY-RUN: Would chmod +x and treat as binary release"
        BINARY_RELEASE=true
    else
        if ask_yes_no \
            "Make lmstudio-tray-manager executable (chmod +x) and continue as binary release?"; then
            log_output "INFO" "User accepted to make binary executable"
            if chmod +x "$SCRIPT_DIR/lmstudio-tray-manager"; then
                print_step "Binary made executable"
                log_output "INFO" "Successfully made binary executable"
                BINARY_RELEASE=true
            else
                print_error "Failed to chmod +x lmstudio-tray-manager"
                log_output "ERROR" "Failed to chmod +x lmstudio-tray-manager"
                exit 1
            fi
        else
            log_output "ERROR" \
                "User declined to make binary executable - cannot continue"
            print_error \
                "Binary exists but is not executable; cannot continue safely. Setup cancelled."
            print_info "Fix permissions and re-run: chmod +x ./lmstudio-tray-manager"
            exit 1
        fi
    fi
else
    print_info "Python package release detected"
    log_output "INFO" \
        "Python package (source) release detected - no binary executable found"
    print_info "Python virtual environment will be created"
fi

# ============================================================================
# 4. Check GTK3/GObject typelibs (required by both binary and Python releases)
# ============================================================================

check_gtk_typelibs() {
    if command -v python3 >/dev/null 2>&1; then
        python3 - <<'PYCODE' >/dev/null 2>&1
import gi
try:
    gi.require_version("Gtk", "3.0")
    # indicator namespace may be either AyatanaAppIndicator3 or AppIndicator3
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
    except ValueError:
        gi.require_version("AppIndicator3", "0.1")
    from gi.repository import Gtk
except Exception:
    raise
PYCODE
        return $?
    fi
    if [ ! -f "/usr/lib/girepository-1.0/Gtk-3.0.typelib" ]; then
        return 1
    fi
    if [ ! -f "/usr/lib/girepository-1.0/AyatanaAppIndicator3-0.1.typelib" ] && \
       [ ! -f "/usr/lib/girepository-1.0/AppIndicator3-0.1.typelib" ]; then
        return 1
    fi
    return 0
}


echo -e "\n${BLUE}Step 4: Checking GTK3/GObject typelibs${NC}"
log_output "INFO" "Step 4: Checking for GTK3/GObject typelibs"

if [ "$APPIMAGE_RELEASE" = true ]; then
    print_step "Skipped (AppImage bundles its own GTK3 runtime)"
    log_output "INFO" \
        "Step 4: Skipped GTK3 check (AppImage release bundles its own GTK3)"
elif check_gtk_typelibs; then
    print_step "GTK3/GObject typelibs already available"
    log_output "INFO" "GTK3/GObject typelibs detected"
else
    print_warning "GTK3/GObject typelibs not found"
    log_output "WARN" "GTK3/GObject typelibs missing"
    echo ""
    print_info "The application requires GTK3/GObject typelibs (gir1.2-gtk-3.0),"
    print_info "an AppIndicator3 typelib (gir1.2-ayatanaappindicator3-0.1 or the"
    print_info "equivalent package for your distribution), and the Python3 GObject"
    print_info "bindings package (python3-gi)."
    if [ "$DRY_RUN" = "1" ]; then
        print_info "[DRY-RUN] Would install gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 python3-gi"
        log_output "INFO" "DRY-RUN: GTK typelibs and python3-gi installation skipped"
    else
        if ask_yes_no "Install required GTK3, AppIndicator, and python3-gi packages now?"; then
            log_output "INFO" "User chose to install GTK3 typelibs and python3-gi"
            echo "Updating package manager..."
            log_output "INFO" "Running apt update"
            sudo apt update
            echo "Installing GTK3, AppIndicator typelibs, and python3-gi..."
            log_output "INFO" "Installing packages: gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 python3-gi"
            if sudo apt install -y gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 python3-gi; then
                print_step "GTK3 typelibs and python3-gi installed successfully"
                log_output "INFO" "GTK3 typelibs and python3-gi installed successfully"
            else
                print_error "Failed to install GTK3 typelibs"
                log_output "ERROR" "apt install failed for GTK3 typelibs"
                exit 1
            fi
        else
            log_output "ERROR" "User declined GTK3 typelibs installation - setup cancelled"
            print_error "GTK3/GObject libraries are required. Setup cancelled."
            exit 1
        fi
    fi
fi

# ============================================================================
# 5. Check Python + PyGObject compatibility (only for Python package releases)
# ============================================================================
if [ "$BINARY_RELEASE" = false ]; then
    echo -e "\n${BLUE}Step 5: Checking Python + PyGObject compatibility${NC}"
    log_output "INFO" "Step 5: Looking for Python interpreter with working gi"

    PYTHON_PATH=""
    for candidate in \
        python3 \
        python3.13 python3.12 python3.11 python3.10 \
        python3.9 python3.8
    do
        if ! command -v "$candidate" >/dev/null 2>&1; then
            continue
        fi

        CANDIDATE_PATH=$(command -v "$candidate")
        if "$CANDIDATE_PATH" - <<'PYCODE' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: F401
PYCODE
        then
            PYTHON_PATH="$CANDIDATE_PATH"
            break
        fi
    done

    if [ -n "$PYTHON_PATH" ]; then
        PYTHON_VERSION=$("$PYTHON_PATH" --version 2>&1)
        print_step "Compatible Python interpreter found"
        echo "   $PYTHON_VERSION"
        echo "   Path: $PYTHON_PATH"
        log_output "INFO" "Compatible interpreter: $PYTHON_VERSION ($PYTHON_PATH)"
    else
        print_warning "No Python interpreter with working PyGObject found"
        log_output "WARN" "No interpreter with successful gi import"
        echo ""
        print_info "No installed Python on this system can currently import gi."
        print_info "The setup needs a Python interpreter with GTK3/PyGObject support."

        if [ "$DRY_RUN" = "1" ]; then
            print_info "[DRY-RUN] Would install: python3 python3-venv python3-gi"
            print_info "[DRY-RUN] Would then re-check gi import with python3"
            log_output "INFO" "DRY-RUN: Would install python3/python3-venv/python3-gi"
        else
            if ask_yes_no "Install python3, python3-venv and python3-gi now?"; then
                log_output "INFO" "User accepted Python + PyGObject installation"
                echo "Updating package manager..."
                log_output "INFO" "Running apt update"
                sudo apt update
                echo "Installing python3, python3-venv and python3-gi..."
                log_output "INFO" "Installing packages: python3 python3-venv python3-gi"
                if ! sudo apt install -y python3 python3-venv python3-gi; then
                    print_error "Failed to install Python/PyGObject packages"
                    log_output "ERROR" "apt install failed for python3 python3-venv python3-gi"
                    exit 1
                fi

                if command -v python3 >/dev/null 2>&1 && \
                   python3 - <<'PYCODE' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: F401
PYCODE
                then
                    PYTHON_PATH=$(command -v python3)
                    PYTHON_VERSION=$("$PYTHON_PATH" --version 2>&1)
                    print_step "Compatible Python interpreter installed"
                    echo "   $PYTHON_VERSION"
                    echo "   Path: $PYTHON_PATH"
                    log_output "INFO" "Interpreter installed and validated: $PYTHON_VERSION ($PYTHON_PATH)"
                else
                    print_error "python3 was installed, but gi import still fails"
                    print_info "Use binary release or install matching PyGObject packages"
                    print_info "for one local Python interpreter, then run setup again."
                    log_output "ERROR" "Post-install gi validation failed"
                    exit 1
                fi
            else
                print_error "A Python interpreter with working PyGObject is required."
                print_info "Alternatively, use the binary release without Python setup."
                log_output "ERROR" "User declined Python/PyGObject installation"
                exit 1
            fi
        fi
    fi
fi

# ============================================================================
# 6. Create Python Virtual Environment (only for Python package)
# ============================================================================
if [ "$BINARY_RELEASE" = false ]; then
    echo -e "\n${BLUE}Step 6: Creating Python Virtual Environment${NC}"
    log_output "INFO" "Step 6: Creating Python virtual environment"

    if [ "$DRY_RUN" = "1" ]; then
        if [ -d "$VENV_DIR" ]; then
            print_info "[DRY-RUN] Would remove existing venv: $VENV_DIR"
            log_output "INFO" "DRY-RUN: Would remove existing venv at $VENV_DIR"
        fi
        print_info "[DRY-RUN] Would create venv: ${PYTHON_PATH:-python3} -m venv --system-site-packages $VENV_DIR"
        print_info "[DRY-RUN] Would upgrade pip/setuptools in venv"
        log_output "INFO" "DRY-RUN: Would create venv and upgrade pip/setuptools"
        print_step "Dry-run: venv step simulated"
    else
        if [ -d "$VENV_DIR" ]; then
            print_warning "Removing existing venv..."
            log_output "WARN" "Existing venv found at $VENV_DIR - removing"

            case "$VENV_DIR" in
                ""|"/"|"."|".." )
                    print_error "Refusing to remove unsafe venv path: '$VENV_DIR'"
                    log_output "ERROR" "Unsafe venv path detected: '$VENV_DIR' - refusing to remove"
                    exit 1
                    ;;
            esac

            VENV_ABS="$(cd "$SCRIPT_DIR" && cd "$VENV_DIR" 2>/dev/null && pwd -P)"
            SCRIPT_ABS="$(cd "$SCRIPT_DIR" && pwd -P)"
            log_output "DEBUG" "Venv absolute path: $VENV_ABS"
            log_output "DEBUG" "Script absolute path: $SCRIPT_ABS"
            if [ -z "$VENV_ABS" ]; then
                print_error "Cannot resolve venv path '$VENV_DIR' (symlink or permission issue)"
                log_output "ERROR" "Failed to resolve absolute path for venv '$VENV_DIR'"
                exit 1
            fi
            case "$VENV_ABS" in
                "$SCRIPT_ABS"/*)
                    log_output "INFO" "Venv path validated - removing $VENV_DIR"
                    rm -rf "$VENV_DIR"
                    ;;
                *)
                    print_error "Refusing to remove venv outside script dir: '$VENV_DIR'"
                    log_output "ERROR" "Venv path '$VENV_DIR' is outside script directory - refusing to remove"
                    exit 1
                    ;;
            esac
        fi

        echo "Creating venv with system site-packages (for PyGObject/GTK3)..."
        log_output "INFO" "Creating Python venv at $VENV_DIR with system-site-packages"
        if "${PYTHON_PATH:-python3}" -m venv --system-site-packages "$VENV_DIR"; then
            print_step "Virtual environment created"
            log_output "INFO" "Virtual environment created successfully at $VENV_DIR"
        else
            print_error "Failed to create virtual environment"
            log_output "ERROR" "Failed to create venv at $VENV_DIR"
            exit 1
        fi

        print_info "Upgrading pip and setuptools..."
        log_output "INFO" "Upgrading pip and setuptools in venv"
        if "$VENV_DIR/bin/python3" -m pip install --upgrade pip setuptools >/dev/null 2>&1; then
            print_step "pip and setuptools upgraded"
            pip_version=$("$VENV_DIR/bin/python3" -m pip --version 2>&1)
            log_output "INFO" "pip and setuptools upgraded successfully - $pip_version"
        else
            print_warning "Could not upgrade pip/setuptools (may continue anyway)"
            log_output "WARN" "Failed to upgrade pip/setuptools - continuing anyway"
        fi

        if "$VENV_DIR/bin/python3" - <<'PYCODE' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: F401
PYCODE
        then
            print_step "Verified: gi import works in venv"
            log_output "INFO" "gi import test succeeded in venv"
        else
            print_error "gi import fails in venv despite compatible system interpreter"
            log_output "ERROR" "gi import test failed in venv"
            exit 1
        fi
    fi
else
    echo -e "\n${BLUE}Step 6: Python Virtual Environment${NC}"
    print_step "Skipped (using binary release)"
    log_output "INFO" "Step 6: Skipped venv creation (binary release)"
fi

# ============================================================================
# 7. Summary
# ============================================================================
echo -e "\n${GREEN}═══════════════════════════════════════${NC}"
if [ "$DRY_RUN" = "1" ]; then
    echo -e "${GREEN}✓ Dry-run completed successfully!${NC}"
    log_output "INFO" "Dry-run completed successfully!"
else
    echo -e "${GREEN}✓ Setup completed successfully!${NC}"
    log_output "INFO" "Setup completed successfully!"
fi
echo -e "${GREEN}═══════════════════════════════════════${NC}"
echo ""
print_info "Next steps:"

if [ "$APPIMAGE_RELEASE" = true ]; then
    _appimg_basename="$(basename "$APPIMAGE_FILE")"
    log_output "INFO" "AppImage release - showing AppImage usage instructions"
    print_info "  🖼️  Using AppImage release"
    print_info ""
    print_info "  1. Auto-start with daemon (recommended):"
    print_info "     ./$_appimg_basename --auto-start-daemon"
    print_info ""
    print_info "  2. Start GUI (stops daemon first):"
    print_info "     ./$_appimg_basename --gui"
    print_info ""
    print_info "  3. Debug mode (verbose logging):"
    print_info "     ./$_appimg_basename --debug"
    print_info ""
    print_info "  4. Monitor specific model:"
    print_info "     ./$_appimg_basename qwen2.5:7b-instruct"
    print_info ""
    print_info "  5. View all options:"
    print_info "     ./$_appimg_basename --help"
elif [ "$BINARY_RELEASE" = true ]; then
    log_output "INFO" "Binary release detected - showing binary usage instructions"
    print_info "  📦 Using pre-built binary release"
    print_info ""
    print_info "  1. Auto-start with daemon (recommended):"
    print_info "     ./lmstudio-tray-manager --auto-start-daemon"
    print_info ""
    print_info "  2. Start GUI (stops daemon first):"
    print_info "     ./lmstudio-tray-manager --gui"
    print_info ""
    print_info "  3. Debug mode (verbose logging):"
    print_info "     ./lmstudio-tray-manager --debug"
    print_info ""
    print_info "  4. Monitor specific model:"
    print_info "     ./lmstudio-tray-manager qwen2.5:7b-instruct"
    print_info ""
    print_info "  5. View all options:"
    print_info "     ./lmstudio-tray-manager --help"
else
    log_output "INFO" "Source release detected - showing Python usage instructions"
    print_info "  1. Run the automation script:"
    print_info "     ./lmstudio_autostart.sh"
    print_info "     (If dist/lmstudio-tray-manager exists, it is used automatically)"
    print_info ""
    print_info "  2. Or use with specific options:"
    print_info "     ./lmstudio_autostart.sh --model qwen2.5:7b-instruct"
    print_info "     ./lmstudio_autostart.sh --list-models"
    print_info "     ./lmstudio_autostart.sh --debug"
fi

print_info ""
print_info "For more information, see:"
print_info "  - README.md"
print_info "  - docs/SETUP.md"
log_output "INFO" "Setup script completed - user instructions displayed"
print_info "  - docs/index.html"
print_info ""
print_info "Log file saved to: $LOGFILE"
log_output "INFO" "Setup process finished at $(date '+%Y-%m-%d %H:%M:%S')"
print_info ""
