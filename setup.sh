#!/usr/bin/env bash
# Setup script for LM Studio automation
# Checks for LM Studio daemon, desktop app, and sets up Python venv
# Linux only

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
LOGS_DIR="$SCRIPT_DIR/.logs"
LOGFILE="$LOGS_DIR/setup.log"

# Create .logs directory if it doesn't exist
mkdir -p "$LOGS_DIR"

# Create/clear logfile with timestamp
cat > "$LOGFILE" << EOF
================================================================================
LM Studio Setup Log
Started: $(date '+%Y-%m-%d %H:%M:%S')
================================================================================
EOF

# Function to log messages to file and display them
log_output() {
    local level="$1"
    shift
    local message="$*"
    
    # Format for log file
    local log_entry
    log_entry="[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $message"
    
    # Write to log file
    echo "$log_entry" >> "$LOGFILE"
}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Utility functions
print_header() {
    local header="═══════════════════════════════════════"
    echo -e "${BLUE}$header${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}$header${NC}"
    
    # Log without colors
    log_output "INFO" "--- $1 ---"
}

print_step() {
    echo -e "${GREEN}✓${NC} $1"
    log_output "OK" "$1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
    log_output "ERROR" "$1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
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
        read -p "$(echo -e "${YELLOW}""$prompt""${NC}" [y/n]: )" -r response
        case "$response" in
            [yY][eE][sS]|[yY])
                return 0
                ;;
            [nN][oO]|[nN])
                return 1
                ;;
            *)
                echo "Please answer y or n"
                ;;
        esac
    done
}

# Check OS
if [[ "$OSTYPE" != "linux"* ]]; then
    print_error "This script only works on Linux"
    exit 1
fi

print_header "LM Studio Automation Setup"

# ============================================================================
# 1. Check LM Studio Daemon (Headless)
# ============================================================================
echo -e "\n${BLUE}Step 1: Checking LM Studio Daemon Installation${NC}"

if command -v lms >/dev/null 2>&1 || [ -x "$HOME/.lmstudio/bin/lms" ]; then
    print_step "LM Studio daemon found"
    LMS_CLI=$(command -v lms 2>/dev/null || echo "$HOME/.lmstudio/bin/lms")
    echo "   Location: $LMS_CLI"
else
    print_warning "LM Studio daemon not found"
    echo ""
    print_info "The LM Studio daemon (llmster) is required for the automation scripts."
    print_info "You can download it from: https://lmstudio.ai/download"
    echo ""
    if ask_yes_no "Would you like to download LM Studio daemon?"; then
        print_info "Opening LM Studio download page..."
        if command -v xdg-open >/dev/null 2>&1; then
            xdg-open "https://lmstudio.ai/download" &
        elif command -v firefox >/dev/null 2>&1; then
            firefox "https://lmstudio.ai/download" &
        else
            print_info "Please visit: https://lmstudio.ai/download"
        fi
        print_error "Please install LM Studio daemon and run this script again"
        exit 1
    else
        print_error "LM Studio daemon is required. Setup cancelled."
        exit 1
    fi
fi

# ============================================================================
# 2. Check LM Studio Desktop App
# ============================================================================
echo -e "\n${BLUE}Step 2: Checking LM Studio Desktop App${NC}"

FOUND_DEB=false
FOUND_APPIMAGE=false
APP_INSTALLED=false

# Check for .deb package
if dpkg -l | grep -q lm-studio; then
    print_step "LM Studio desktop app found (deb package)"
    APP_INSTALLED=true
    FOUND_DEB=true
fi

# Check for App Image in common locations (including current script directory)
for appimage_path in "$SCRIPT_DIR" "$HOME/LM_Studio" "$HOME/Applications" "$HOME/.local/bin" "$HOME/Apps" "/opt/lm-studio"; do
    if [ -d "$appimage_path" ]; then
        for appimage_file in "$appimage_path"/*.AppImage "$appimage_path"/LM-Studio* "$appimage_path"/LM\ Studio*; do
            if [ -f "$appimage_file" ]; then
                print_step "LM Studio desktop app found (AppImage)"
                APP_INSTALLED=true
                FOUND_APPIMAGE=true
                APPIMAGE_PATH="$appimage_path"
                break 2
            fi
        done
    fi
done

if [ "$APP_INSTALLED" = false ]; then
    print_warning "LM Studio desktop app not found"
    echo ""
    print_info "The desktop app is required for the --gui option."
    print_info "Choose installation method:"
    print_info "  1) Install .deb package (recommended for Ubuntu/Debian)"
    print_info "  2) Use AppImage (manual download)"
    print_info "  3) Skip (can be installed later)"
    echo ""
    read -p "Choose option [1-3]: " -r app_choice
    
    case "$app_choice" in
        1)
            echo "Opening LM Studio download page..."
            if command -v xdg-open >/dev/null 2>&1; then
                xdg-open "https://lmstudio.ai/download" &
            elif command -v firefox >/dev/null 2>&1; then
                firefox "https://lmstudio.ai/download" &
            else
                echo "Please visit: https://lmstudio.ai/download"
            fi
            print_warning "Please download and install the .deb package, then run this script again"
            ;;
        2)
            print_info "Enter path to AppImage file (or directory containing it): "
            read -r appimage_input
            if [ -f "$appimage_input" ]; then
                APPIMAGE_PATH="$appimage_input"
                print_step "AppImage path set to: $APPIMAGE_PATH"
                APP_INSTALLED=true
            elif [ -d "$appimage_input" ]; then
                APPIMAGE_PATH="$appimage_input"
                print_step "AppImage directory set to: $APPIMAGE_PATH"
                APP_INSTALLED=true
            else
                print_error "Invalid path: $appimage_input"
            fi
            ;;
        3)
            print_warning "Desktop app installation skipped. The --gui option won't work until you install it."
            ;;
        *)
            print_error "Invalid option"
            ;;
    esac
fi

if [ "$APP_INSTALLED" = true ]; then
    if [ "$FOUND_DEB" = true ]; then
        echo "   Desktop app: deb package"
    elif [ -n "$APPIMAGE_PATH" ]; then
        echo "   Desktop app: AppImage at $APPIMAGE_PATH"
    fi
fi

# ============================================================================
# 3. Check Python 3.10
# ============================================================================
echo -e "\n${BLUE}Step 3: Checking Python 3.10${NC}"

if command -v python3.10 >/dev/null 2>&1; then
    print_step "Python 3.10 found"
    PYTHON_VERSION=$(python3.10 --version)
    echo "   $PYTHON_VERSION"
else
    print_warning "Python 3.10 not found"
    echo ""
    echo "Python 3.10 is required for PyGObject/GTK3 compatibility."
    if ask_yes_no "Would you like to install Python 3.10?"; then
        echo "Updating package manager..."
        sudo apt update
        echo "Installing Python 3.10..."
        if sudo apt install -y python3.10 python3.10-venv python3.10-dev; then
            print_step "Python 3.10 installed successfully"
        else
            print_error "Failed to install Python 3.10"
            exit 1
        fi
    else
        print_error "Python 3.10 is required. Setup cancelled."
        exit 1
    fi
fi

# ============================================================================
# 4. Create Python Virtual Environment
# ============================================================================
echo -e "\n${BLUE}Step 4: Creating Python Virtual Environment${NC}"

if [ -d "$VENV_DIR" ]; then
    print_warning "Removing existing venv..."
    rm -rf "$VENV_DIR"
fi

echo "Creating venv with system site-packages (for PyGObject/GTK3)..."
if python3.10 -m venv --system-site-packages "$VENV_DIR"; then
    print_step "Virtual environment created"
else
    print_error "Failed to create virtual environment"
    exit 1
fi

# Upgrade pip and setuptools
print_info "Upgrading pip and setuptools..."
if "$VENV_DIR/bin/python3" -m pip install --upgrade pip setuptools >/dev/null 2>&1; then
    print_step "pip and setuptools upgraded"
else
    print_warning "Could not upgrade pip/setuptools (may continue anyway)"
fi

# ============================================================================
# 5. Summary
# ============================================================================
echo -e "\n${GREEN}═══════════════════════════════════════${NC}"
echo -e "${GREEN}✓ Setup completed successfully!${NC}"
echo -e "${GREEN}═══════════════════════════════════════${NC}"
log_output "INFO" "Setup completed successfully!"
echo ""
print_info "Next steps:"
print_info "  1. Run the automation script:"
print_info "     ./lmstudio_autostart.sh"
echo ""
print_info "  2. Or use with specific options:"
print_info "     ./lmstudio_autostart.sh --model qwen2.5:7b-instruct"
print_info "     ./lmstudio_autostart.sh --list-models"
print_info "     ./lmstudio_autostart.sh --debug"
echo ""
print_info "For more information, see:"
print_info "  - README.md"
print_info "  - docs/VENV_SETUP.md"
print_info "  - docs/index.html"
echo ""
print_info "Log file saved to: $LOGFILE"
log_output "INFO" "Setup process finished at $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
