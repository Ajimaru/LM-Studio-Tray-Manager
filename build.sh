#!/bin/bash
# Build script for LM Studio Tray Manager binary distribution
# Creates optimized standalone binary using PyInstaller

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# === Logging configuration ===
LOGS_DIR="$SCRIPT_DIR/.logs"
mkdir -p "$LOGS_DIR"
LOGFILE="$LOGS_DIR/build.log"

# Initialize log file with header
{
    echo "================================================================================"
    echo "LM Studio Tray Manager Build Log"
    echo "Started: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "================================================================================"
} > "$LOGFILE"

# Redirect all output (stdout and stderr) to log file AND terminal
exec > >(tee -a "$LOGFILE") 2>&1

echo "======================================"
echo "LM Studio Tray Manager Build Script"
echo "======================================"
echo

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Portable file size function (Linux stat -c%s, macOS/BSD stat -f%z)
get_file_size() {
    local file="$1"
    # Try Linux stat
    if stat -c%s "$file" 2>/dev/null; then
        return 0
    fi
    # Try macOS/BSD stat
    if stat -f%z "$file" 2>/dev/null; then
        return 0
    fi
    # Fallback: use wc -c
    if wc -c < "$file" 2>/dev/null; then
        return 0
    fi
    # If all methods fail, echo 0
    echo 0
}

# Choose Python (prefer 3.10 if available)
if command -v python3.10 &> /dev/null; then
    PYTHON_BIN="python3.10"
elif command -v python3 &> /dev/null; then
    PYTHON_BIN="python3"
else
    echo -e "${RED}Error: python3 not found${NC}"
    exit 1
fi

echo -e "${GREEN}✓${NC} Python found: \"$("$PYTHON_BIN" --version)\""

# Create venv if missing (with system site-packages for gi)
if [ -d ".venv" ]; then
    VENV_DIR=".venv"
elif [ -d "venv" ]; then
    VENV_DIR="venv"
else
    VENV_DIR="venv"
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    if ! "$PYTHON_BIN" -m venv --system-site-packages "$VENV_DIR"; then
        echo -e "${RED}Error: Failed to create virtual environment${NC}"
        exit 1
    fi
fi

# If the existing venv points to a python interpreter that no longer
# exists (e.g. the system upgraded from 3.10 to 3.12), the
# ``venv/bin/python`` symlink will be broken and attempts to run it
# fail.  Detect that situation now and recreate the environment from
# scratch using the current $PYTHON_BIN.
if [ -d "$VENV_DIR" ] && [ ! -x "$VENV_DIR/bin/python" ]; then
    echo -e "${YELLOW}Detected broken venv (missing python); recreating...${NC}"
    rm -rf "$VENV_DIR"
    if ! "$PYTHON_BIN" -m venv --system-site-packages "$VENV_DIR"; then
        echo -e "${RED}Error: Failed to recreate virtual environment${NC}"
        exit 1
    fi
fi

# Verify activation script exists
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo -e "${RED}Error: Virtual environment activation script not found at $VENV_DIR/bin/activate${NC}"
    echo -e "${YELLOW}Trying to create virtual environment...${NC}"
    if ! "$PYTHON_BIN" -m venv --system-site-packages "$VENV_DIR" \
        || [ ! -f "$VENV_DIR/bin/activate" ]; then
        echo -e "${RED}Error: Could not create or activate virtual environment${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}✓${NC} Activating virtual environment..."
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

# Use explicit path to venv python
VENV_PYTHON="$VENV_DIR/bin/python"

# ---------------------------------------------------------------------------
# Ensure C compiler exists (required by PyInstaller bootloader build)
# ---------------------------------------------------------------------------

check_compiler() {
    for c in gcc clang; do
        if command -v "$c" &> /dev/null; then
            if "$c" --version >/dev/null 2>&1; then
                return 0
            fi
        fi
    done
    return 1
}

check_zlib() {
    printf 'int main(void){return 0;}' | gcc -x c - -lz -o /dev/null 2>/dev/null
}

if ! check_compiler; then
    echo -e "${YELLOW}No C compiler detected. PyInstaller needs a C compiler to
build its bootloader.${NC}"
    read -p "Install build-essential/clang packages now? [y/n]: " -r response
    case "$response" in
        [yY][eE][sS]|[yY])
            # attempt to install via apt if available
            if command -v apt-get &> /dev/null || command -v apt &> /dev/null; then
                echo -e "${GREEN}Installing build tools via apt...${NC}"
                sudo apt update && sudo apt install -y build-essential
            else
                echo -e "${YELLOW}Unable to install automatically; please install a
C compiler (e.g. gcc or clang, plus make) manually and re-run the script.${NC}"
                echo
                echo -e "${RED}Exiting because compiler is still missing.${NC}"
                exit 1
            fi
            ;;
        *)
            echo -e "${RED}Compiler is required to build the binary. Exiting.${NC}"
            exit 1
            ;;
    esac
    # re-check after attempt
    if ! command -v gcc &> /dev/null && ! command -v clang &> /dev/null; then
        echo -e "${RED}Compiler still not found; cannot continue.${NC}"
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Ensure zlib development library is available (required for bootloader)
# ---------------------------------------------------------------------------
if ! check_zlib; then
    echo -e "${YELLOW}zlib development headers/libraries not detected.\n"\
         "PyInstaller's bootloader links against zlib, so you must install\n"\
         "the zlib-dev package (zlib1g-dev on Debian/Ubuntu).${NC}"
    read -p "Install zlib development package now? [y/n]: " -r response
    case "$response" in
        [yY][eE][sS]|[yY])
            if command -v apt-get &> /dev/null || command -v apt &> /dev/null; then
                echo -e "${GREEN}Installing zlib development package via apt...${NC}"
                sudo apt update && sudo apt install -y zlib1g-dev
            else
                echo -e "${YELLOW}Cannot install automatically; please install zlib1g-dev\n"\
                     "(or equivalent) manually and re-run the script.${NC}"
                echo -e "${RED}Exiting because zlib is still missing.${NC}"
                exit 1
            fi
            ;;
        *)
            echo -e "${RED}zlib development library is required. Exiting.${NC}"
            exit 1
            ;;
    esac
    if ! check_zlib; then
        echo -e "${RED}zlib still not available; cannot continue.${NC}"
        exit 1
    fi
fi

# Ensure PyInstaller is available in the venv
if ! "$VENV_PYTHON" -m PyInstaller --version &> /dev/null; then
    echo -e "${YELLOW}Installing PyInstaller in venv...${NC}"
    "$VENV_PYTHON" -m pip install --upgrade pip
    # Use --require-hashes to enforce integrity verification
    "$VENV_PYTHON" -m pip install --require-hashes -r "$SCRIPT_DIR/requirements-build.txt"

fi

# Clean previous builds
if [ -d "build" ] || [ -d "dist" ]; then
    echo -e "${YELLOW}Cleaning previous builds...${NC}"
    rm -rf build dist
fi

# Run PyInstaller build
echo
echo "Running PyInstaller build..."
"$VENV_PYTHON" build_binary.py

# Check if binary was created
BINARY_PATH="dist/lmstudio-tray-manager"
if [ ! -f "$BINARY_PATH" ]; then
    echo -e "${RED}Binary not found at $BINARY_PATH${NC}"
    exit 1
fi

echo
echo "======================================"
echo "Build Optimization"
echo "======================================"
echo

UNOPT_SIZE=$(get_file_size "$BINARY_PATH")
UNOPT_SIZE_MB=$(awk -v n="$UNOPT_SIZE" 'BEGIN {printf "%.2f", n / 1048576}')
echo "Unoptimized binary size: ${UNOPT_SIZE_MB} MB"

# Strip debug symbols
if command -v strip &> /dev/null; then
    echo -e "${GREEN}Stripping debug symbols...${NC}"
    strip "$BINARY_PATH"
    STRIPPED_SIZE=$(get_file_size "$BINARY_PATH")
    STRIPPED_SIZE_MB=$(awk -v n="$STRIPPED_SIZE" \
        'BEGIN {printf "%.2f", n / 1048576}')
    SAVED_MB=$(awk -v a="$UNOPT_SIZE" -v b="$STRIPPED_SIZE" \
        'BEGIN {printf "%.2f", (a - b) / 1048576}')
    echo "After strip: ${STRIPPED_SIZE_MB} MB (saved ${SAVED_MB} MB)"
else
    echo -e "${YELLOW}Warning: strip not found, skipping...${NC}"
    STRIPPED_SIZE=$UNOPT_SIZE
fi

FINAL_SIZE="$STRIPPED_SIZE"
FINAL_SIZE_MB=$(awk -v n="$FINAL_SIZE" \
    'BEGIN {printf "%.2f", n / 1048576}')

echo
echo "======================================"
echo -e "${GREEN}Build Complete!${NC}"
echo "======================================"
echo
echo "Binary: $BINARY_PATH"
echo "Size: ${FINAL_SIZE_MB} MB"
echo
echo "Test the binary:"
echo "  ./dist/lmstudio-tray-manager --version"
echo "  ./dist/lmstudio-tray-manager --help"
echo
echo "Log: $LOGFILE"
echo "Completed: $(date '+%Y-%m-%d %H:%M:%S')"
