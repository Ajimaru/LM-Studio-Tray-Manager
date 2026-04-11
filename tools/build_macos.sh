#!/bin/bash
# Build a native macOS .app bundle locally.
# Usage: ./tools/build_macos.sh [--clean] [--sign-identity <identity>] [--notary-profile <profile>]
#
# By default this script creates an unsigned Apple Silicon .app bundle.
# Pass --sign-identity to codesign the result and --notary-profile to notarize it.

set -euo pipefail

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="${PROJECT_ROOT}/venv_macos"
BUILD_DIR="${PROJECT_ROOT}/build/macos"
DIST_DIR="${PROJECT_ROOT}/dist"
RELEASE_DIR="${PROJECT_ROOT}/release"
SPEC_DIR="${BUILD_DIR}/spec"
PYINSTALLER_WORK_DIR="${BUILD_DIR}/pyinstaller"
ICON_VECTOR_SOURCE="${PROJECT_ROOT}/assets/img/lm-studio-tray-manager.svg"
ICON_RASTER_SOURCE="${PROJECT_ROOT}/assets/img/lm-studio-tray-manager.png"
ICON_RENDER_DIR="${BUILD_DIR}/quicklook"
ICON_MASTER_PNG="${BUILD_DIR}/LM-Studio-Tray-Manager-master.png"
ICONSET_DIR="${BUILD_DIR}/LM-Studio-Tray-Manager.iconset"
GENERATED_ICON="${BUILD_DIR}/LM-Studio-Tray-Manager.icns"
APP_PATH="${DIST_DIR}/LM-Studio-Tray-Manager.app"
SIGN_IDENTITY=""
NOTARY_PROFILE=""
ARCHIVE_SUFFIX="unsigned"
ICON_PATH=""

cd "$PROJECT_ROOT"

handle_clean_flag() {
    if [[ "${1:-}" == "--clean" ]]; then
        echo -e "${BLUE}🧹 Cleaning previous builds...${NC}"
        rm -rf "$VENV_DIR" "$BUILD_DIR" "$DIST_DIR" "$RELEASE_DIR"
        echo -e "${GREEN}✅ Cleaned${NC}"
    fi
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --clean)
                shift
                ;;
            --sign-identity)
                if [[ $# -lt 2 ]]; then
                    echo -e "${RED}❌ --sign-identity requires a value${NC}"
                    exit 1
                fi
                SIGN_IDENTITY="$2"
                shift 2
                ;;
            --notary-profile)
                if [[ $# -lt 2 ]]; then
                    echo -e "${RED}❌ --notary-profile requires a value${NC}"
                    exit 1
                fi
                NOTARY_PROFILE="$2"
                shift 2
                ;;
            *)
                echo -e "${RED}❌ Unknown option: $1${NC}"
                echo "Usage: ./tools/build_macos.sh [--clean] [--sign-identity <identity>] [--notary-profile <profile>]"
                exit 1
                ;;
        esac
    done
}

check_python() {
    echo -e "${BLUE}📋 Checking Python installation...${NC}"

    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}❌ Python 3 not found${NC}"
        echo "Install Python 3.12+ from https://www.python.org/downloads/"
        exit 1
    fi

    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
    PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

    if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 12 ]]; then
        echo -e "${RED}❌ Python 3.12+ required, found $PYTHON_VERSION${NC}"
        echo "Install Python 3.12+ from https://www.python.org/downloads/"
        exit 1
    fi

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

check_macos_tools() {
    echo -e "${BLUE}📋 Checking macOS bundle tooling...${NC}"

    if ! command -v sips &> /dev/null; then
        echo -e "${RED}❌ sips not found${NC}"
        exit 1
    fi

    if ! command -v iconutil &> /dev/null; then
        echo -e "${RED}❌ iconutil not found${NC}"
        exit 1
    fi

    if ! command -v qlmanage &> /dev/null; then
        echo -e "${RED}❌ qlmanage not found${NC}"
        exit 1
    fi

    if ! command -v /usr/libexec/PlistBuddy &> /dev/null; then
        echo -e "${RED}❌ PlistBuddy not found${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ macOS bundle tooling found${NC}"
}

create_venv() {
    echo -e "${BLUE}📦 Creating virtual environment...${NC}"

    mkdir -p "$BUILD_DIR" "$SPEC_DIR" "$PYINSTALLER_WORK_DIR"

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
    python3 -m pip install --require-hashes -r requirements-build.txt --quiet
    python3 -m pip install rumps==0.4.0 --quiet

    echo -e "${GREEN}✅ Dependencies installed${NC}"
}

generate_icon() {
    echo -e "${BLUE}🎨 Generating macOS icon...${NC}"

    rm -rf "$ICON_RENDER_DIR" "$ICONSET_DIR" "$GENERATED_ICON" "$ICON_MASTER_PNG"
    mkdir -p "$ICON_RENDER_DIR" "$ICONSET_DIR"

    if [[ -f "$ICON_VECTOR_SOURCE" ]]; then
        local rendered_icon
        rendered_icon="$ICON_RENDER_DIR/$(basename "$ICON_VECTOR_SOURCE").png"
        qlmanage -t -s 1024 -o "$ICON_RENDER_DIR" "$ICON_VECTOR_SOURCE" >/dev/null 2>&1
        if [[ -f "$rendered_icon" ]]; then
            cp "$rendered_icon" "$ICON_MASTER_PNG"
        fi
    fi

    if [[ ! -f "$ICON_MASTER_PNG" && -f "$ICON_RASTER_SOURCE" ]]; then
        sips -z 1024 1024 "$ICON_RASTER_SOURCE" --out "$ICON_MASTER_PNG" >/dev/null
    fi

    if [[ ! -f "$ICON_MASTER_PNG" ]]; then
        echo -e "${BLUE}⚠️  No icon source found, building without custom icon${NC}"
        ICON_PATH=""
        return
    fi

    for size in 16 32 128 256 512; do
        sips -z "$size" "$size" "$ICON_MASTER_PNG" \
            --out "$ICONSET_DIR/icon_${size}x${size}.png" >/dev/null
        sips -z "$((size * 2))" "$((size * 2))" "$ICON_MASTER_PNG" \
            --out "$ICONSET_DIR/icon_${size}x${size}@2x.png" >/dev/null
    done

    iconutil -c icns "$ICONSET_DIR" -o "$GENERATED_ICON"
    ICON_PATH="$GENERATED_ICON"

    echo -e "${GREEN}✅ ICNS icon generated${NC}"
}

build_pyinstaller() {
    echo -e "${BLUE}🔨 Building with PyInstaller...${NC}"

    local pyinstaller_args=(
        --noconfirm
        --clean
        --windowed
        --onedir
        --name=LM-Studio-Tray-Manager
        --distpath="$DIST_DIR"
        --workpath="$PYINSTALLER_WORK_DIR"
        --specpath="$SPEC_DIR"
        --osx-bundle-identifier=com.lmstudio.tray-manager
        --target-architecture=arm64
        --add-data "$PROJECT_ROOT/VERSION"":."
        --add-data "$PROJECT_ROOT/AUTHORS"":."
        --add-data "$PROJECT_ROOT/assets"":assets"
        lmstudio_tray.py
    )

    if [[ -n "$ICON_PATH" ]]; then
        pyinstaller_args+=("--icon=$ICON_PATH")
    fi

    python3 -m PyInstaller "${pyinstaller_args[@]}"

    local binary_path="$APP_PATH/Contents/MacOS/LM-Studio-Tray-Manager"

    if [[ ! -f "$binary_path" ]]; then
        echo -e "${RED}❌ PyInstaller build failed${NC}"
        exit 1
    fi

    echo -e "${GREEN}✅ .app bundle created${NC}"
    ls -lh "$binary_path"
}

configure_app_bundle() {
    echo -e "${BLUE}🧩 Configuring app bundle metadata...${NC}"

    local plist_path="$APP_PATH/Contents/Info.plist"

    /usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$plist_path" 2>/dev/null || \
        /usr/libexec/PlistBuddy -c "Set :LSUIElement true" "$plist_path"
    /usr/libexec/PlistBuddy -c "Add :NSHighResolutionCapable bool true" "$plist_path" 2>/dev/null || \
        /usr/libexec/PlistBuddy -c "Set :NSHighResolutionCapable true" "$plist_path"
    /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string LM Studio Tray Manager" "$plist_path" 2>/dev/null || \
        /usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName LM Studio Tray Manager" "$plist_path"
    /usr/libexec/PlistBuddy -c "Add :CFBundleName string LM Studio Tray Manager" "$plist_path" 2>/dev/null || \
        /usr/libexec/PlistBuddy -c "Set :CFBundleName LM Studio Tray Manager" "$plist_path"

    echo -e "${GREEN}✅ App bundle configured${NC}"
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

codesign_app() {
    if [[ -z "$SIGN_IDENTITY" ]]; then
        echo -e "${BLUE}ℹ️  Skipping code signing (no --sign-identity provided)${NC}"
        return
    fi

    echo -e "${BLUE}🔏 Code signing app bundle...${NC}"
    codesign --force --deep --options runtime --sign "$SIGN_IDENTITY" "$APP_PATH"
    codesign --verify --deep --strict --verbose=2 "$APP_PATH"
    ARCHIVE_SUFFIX="signed"
    echo -e "${GREEN}✅ App bundle signed${NC}"
}

notarize_app() {
    if [[ -z "$NOTARY_PROFILE" ]]; then
        echo -e "${BLUE}ℹ️  Skipping notarization (no --notary-profile provided)${NC}"
        return
    fi

    if [[ -z "$SIGN_IDENTITY" ]]; then
        echo -e "${RED}❌ Notarization requires --sign-identity${NC}"
        exit 1
    fi

    if ! xcrun notarytool --help >/dev/null 2>&1; then
        echo -e "${RED}❌ xcrun notarytool is not available${NC}"
        exit 1
    fi

    echo -e "${BLUE}🧾 Notarizing app bundle...${NC}"

    local notarize_zip="${BUILD_DIR}/LM-Studio-Tray-Manager-notarize.zip"
    rm -f "$notarize_zip"

    ditto -c -k --keepParent "$APP_PATH" "$notarize_zip"
    xcrun notarytool submit "$notarize_zip" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$APP_PATH"
    xcrun stapler validate "$APP_PATH"

    ARCHIVE_SUFFIX="notarized"
    echo -e "${GREEN}✅ App bundle notarized and stapled${NC}"
}

create_release_archive() {
    echo -e "${BLUE}📦 Creating release archive...${NC}"

    VERSION=$(cat VERSION)
    mkdir -p "$RELEASE_DIR"

    ARCHIVE_NAME="lmstudio-tray-manager-${VERSION}-macos-${ARCHIVE_SUFFIX}.tar.gz"

    tar -czf "$RELEASE_DIR/$ARCHIVE_NAME" \
        -C "$DIST_DIR" \
        LM-Studio-Tray-Manager.app

    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$RELEASE_DIR/$ARCHIVE_NAME" > "$RELEASE_DIR/SHA256SUMS-macos.txt"
    else
        shasum -a 256 "$RELEASE_DIR/$ARCHIVE_NAME" > "$RELEASE_DIR/SHA256SUMS-macos.txt"
    fi

    echo -e "${GREEN}✅ Release archive created${NC}"
    echo ""
    echo "📦 Archive: $ARCHIVE_NAME"
    ls -lh "$RELEASE_DIR/$ARCHIVE_NAME"
    echo ""
    echo "🔐 Checksum:"
    cat "$RELEASE_DIR/SHA256SUMS-macos.txt"
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
    echo "   open dist/LM-Studio-Tray-Manager.app"
    echo ""
    echo "📦 Release archive:"
    ls -1 "$RELEASE_DIR"/lmstudio-tray-manager-*-macos-*.tar.gz
    echo ""
    echo "Next steps:"
    echo "  1. Launch the native .app bundle from Finder or with 'open'"
    echo "  2. Sign with --sign-identity when preparing a distributable build"
    echo "  3. Notarize with --notary-profile to satisfy Gatekeeper for external users"
    echo ""
}

main() {
    parse_args "$@"
    handle_clean_flag "$@"
    check_python
    check_xcode
    check_macos_tools
    create_venv
    install_dependencies
    generate_icon
    build_pyinstaller
    configure_app_bundle
    copy_resources
    codesign_app
    notarize_app
    create_release_archive
    print_next_steps
}

main "$@"
