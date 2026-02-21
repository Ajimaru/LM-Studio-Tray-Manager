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
    "$PYTHON_BIN" -m venv --system-site-packages "$VENV_DIR"
fi

echo -e "${GREEN}✓${NC} Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Ensure PyInstaller is available in the venv
if ! python -m PyInstaller --version &> /dev/null; then
    echo -e "${YELLOW}Installing PyInstaller in venv...${NC}"
    python -m pip install --upgrade pip
    pip install pyinstaller==6.11.1

fi

# Clean previous builds
if [ -d "build" ] || [ -d "dist" ]; then
    echo -e "${YELLOW}Cleaning previous builds...${NC}"
    rm -rf build dist
fi

# Run PyInstaller build
echo
echo "Running PyInstaller build..."
"$PYTHON_BIN" build_binary.py

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

# Get unoptimized size
UNOPT_SIZE=$(get_file_size "$BINARY_PATH")
UNOPT_SIZE_MB=$(echo "scale=2; $UNOPT_SIZE / 1048576" | bc)
echo "Unoptimized size: ${UNOPT_SIZE_MB} MB"

# Strip debug symbols
if command -v strip &> /dev/null; then
    echo -e "${GREEN}Stripping debug symbols...${NC}"
    strip "$BINARY_PATH"
    STRIPPED_SIZE=$(get_file_size "$BINARY_PATH")
    STRIPPED_SIZE_MB=$(echo "scale=2; $STRIPPED_SIZE / 1048576" | bc)
    SAVED_MB=$(echo "scale=2; ($UNOPT_SIZE - $STRIPPED_SIZE) / 1048576" \
        | bc)
    echo "After strip: ${STRIPPED_SIZE_MB} MB (saved ${SAVED_MB} MB)"
else
    echo -e "${YELLOW}Warning: strip not found, skipping...${NC}"
    STRIPPED_SIZE=$UNOPT_SIZE
fi

# Compress with UPX
if command -v upx &> /dev/null; then
    echo -e "${GREEN}Compressing with UPX...${NC}"
    upx --best --lzma "$BINARY_PATH" 2>/dev/null || upx --best \
        "$BINARY_PATH"
    FINAL_SIZE=$(get_file_size "$BINARY_PATH")
    FINAL_SIZE_MB=$(echo "scale=2; $FINAL_SIZE / 1048576" | bc)
    TOTAL_SAVED=$(echo "scale=2; ($UNOPT_SIZE - $FINAL_SIZE) / 1048576" | bc)
    DIFF_BYTES=$((UNOPT_SIZE - FINAL_SIZE))
    REDUCTION=$(echo "scale=1; ($DIFF_BYTES * 100) / $UNOPT_SIZE" | bc)
    echo "Final size: ${FINAL_SIZE_MB} MB (saved ${TOTAL_SAVED} MB, ${REDUCTION}% reduction)"
else
    echo -e "${YELLOW}Warning: upx not found, skipping compression${NC}"
    echo "Install upx for better compression: sudo apt install upx"
    FINAL_SIZE=$STRIPPED_SIZE
    FINAL_SIZE_MB=$(echo "scale=2; $FINAL_SIZE / 1048576" | bc)
fi

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
