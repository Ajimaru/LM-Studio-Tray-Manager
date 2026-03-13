#!/bin/bash
# Build macOS .app bundle locally for testing
# Usage: ./build_macos.sh [--clean]
#
# This script creates an unsigned .app bundle for local testing.
# Code Signing will be added later for distribution.

set -euo pipefail

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
VENV_DIR="${PROJECT_ROOT}/venv_macos"
BUILD_DIR="${PROJECT_ROOT}/build"
DIST_DIR="${PROJECT_ROOT}/dist"
RELEASE_DIR="${PROJECT_ROOT}/release"

handle_clean_flag() {
    if [[ "${1:-}" == "--clean" ]]; then
        echo -e "${BLUE}🧹 Cleaning previous builds...${NC}"
        rm -rf "$VENV_DIR" "$BUILD_DIR" "$DIST_DIR" "$RELEASE_DIR"
        echo -e "${GREEN}✅ Cleaned${NC}"
    fi
}

check_python() {
    echo -e "${BLUE}📋 Checking Python installation...${NC}"
    
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}❌ Python 3 not found${NC}"
        echo "Install Python 3.12 from https://www.python.org/downloads/"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    echo -e "${GREEN}✅ Python $PYTHON_VERSION found${NC}"
}

check_xcode() {
    echo -e "${BLUE}📋 Checking Xcode Command Line Tools...${NC}"
    
    if ! command -v clang &> /dev/null; then
        echo -e "${RED}❌ Xcode Command Line Tools not found${NC}"
        echo "Install with: xcode-select --install"
        exit 1
    fi
    
    echo -e "${GREEN}✅ Xcode Command Line Tools found${NC}"
}

create_venv() {
    echo -e "${BLUE}📦 Creating virtual environment...${NC}"
    
    if [[ ! -d "$VENV_DIR" ]]; then
        python3 -m venv "$VENV_DIR"
    fi
    
    # shellcheck source=/dev/null
    source "$VENV_DIR/bin/activate"
    echo -e "${GREEN}✅ Virtual environment ready${NC}"
}

install_dependencies() {
    echo -e "${BLUE}📥 Installing build dependencies...${NC}"
    
    python3 -m pip install --upgrade pip setuptools wheel --quiet
    python3 -m pip install -r requirements-build.txt --quiet
    python3 -m pip install rumps --quiet
    
    echo -e "${GREEN}✅ Dependencies installed${NC}"
}

build_pyinstaller() {
    echo -e "${BLUE}🔨 Building with PyInstaller...${NC}"
    
    python3 -m PyInstaller \
        --onedir \
        --name=LM-Studio-Tray-Manager \
        --clean \
        --osx-bundle-identifier=com.lmstudio.tray-manager \
        --add-data VERSION:. \
        --add-data AUTHORS:. \
        --add-data assets:assets \
        --icon=assets/img/lm-studio-tray-manager.icns 2>/dev/null || \
    python3 -m PyInstaller \
        --onedir \
        --name=LM-Studio-Tray-Manager \
        --clean \
        --osx-bundle-identifier=com.lmstudio.tray-manager \
        --add-data VERSION:. \
        --add-data AUTHORS:. \
        --add-data assets:assets \
        lmstudio_tray.py
    
    APP_PATH="$DIST_DIR/LM-Studio-Tray-Manager.app"
    BINARY_PATH="$APP_PATH/Contents/MacOS/LM-Studio-Tray-Manager"
    
    if [[ ! -f "$BINARY_PATH" ]]; then
        echo -e "${RED}❌ PyInstaller build failed${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✅ .app bundle created${NC}"
    ls -lh "$BINARY_PATH"
}

copy_resources() {
    echo -e "${BLUE}📋 Copying resources to .app bundle...${NC}"
    
    APP_RESOURCES="$DIST_DIR/LM-Studio-Tray-Manager.app/Contents/Resources"
    
    cp -v setup.sh "$APP_RESOURCES/"
    cp -v lmstudio_autostart.sh "$APP_RESOURCES/"
    cp -v README.md "$APP_RESOURCES/"
    cp -v LICENSE "$APP_RESOURCES/"
    cp -v AUTHORS "$APP_RESOURCES/"
    
    if [[ -d docs ]]; then
        cp -r docs "$APP_RESOURCES/"
    fi
    
    echo -e "${GREEN}✅ Resources copied${NC}"
}

create_release_archive() {
    echo -e "${BLUE}📦 Creating release archive...${NC}"
    
    VERSION=$(cat VERSION)
    mkdir -p "$RELEASE_DIR"
    
    ARCHIVE_NAME="lmstudio-tray-manager-${VERSION}-macos-unsigned.tar.gz"
    
    tar -czf "$RELEASE_DIR/$ARCHIVE_NAME" \
        -C "$DIST_DIR" \
        LM-Studio-Tray-Manager.app
    
    cd "$RELEASE_DIR"
    sha256sum "$ARCHIVE_NAME" > "SHA256SUMS-macos.txt"
    
    echo -e "${GREEN}✅ Release archive created${NC}"
    echo ""
    echo "📦 Archive: $ARCHIVE_NAME"
    ls -lh "$ARCHIVE_NAME"
    echo ""
    echo "🔐 Checksum:"
    cat "SHA256SUMS-macos.txt"
}

print_next_steps() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}✅ Build complete!${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
    echo ""
    echo "📍 Location: dist/LM-Studio-Tray-Manager.app"
    echo ""
    echo "🧪 Test the app:"
    echo "   dist/LM-Studio-Tray-Manager.app/Contents/MacOS/LM-Studio-Tray-Manager"
    echo ""
    echo "📦 Release archive:"
    ls -1 release/lmstudio-tray-manager-*-macos-unsigned.tar.gz
    echo ""
    echo "Next steps:"
    echo "  1. Test the unsigned app (basic functionality only)"
    echo "  2. For distribution, add Code Signing:"
    echo "     - Get a Developer ID Certificate from Apple Developer Program"
    echo "     - Run: codesign --force --deep --sign '...' dist/LM-Studio-Tray-Manager.app"
    echo "     - Submit for notarization"
    echo ""
}

main() {
    handle_clean_flag "$@"
    check_python
    check_xcode
    create_venv
    install_dependencies
    build_pyinstaller
    copy_resources
    create_release_archive
    print_next_steps
}

main "$@"
