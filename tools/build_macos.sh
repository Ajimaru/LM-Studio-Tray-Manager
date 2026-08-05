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
# The bundle is single-architecture: PyInstaller can only ship what the
# host Python provides. Release names carry it so an Intel user does not
# download an arm64-only build.
TARGET_ARCH="${TARGET_ARCH:-$(uname -m)}"
# Without --keychain, notarytool stores the profile in the iCloud-managed
# "Local Items" keychain, where it can disappear between runs. A dedicated
# keychain keeps it put; picked up automatically when it exists.
NOTARY_KEYCHAIN="${NOTARY_KEYCHAIN:-}"
DEFAULT_NOTARY_KEYCHAIN="$HOME/Library/Keychains/notary.keychain-db"
# Only unsigned builds are marked. A signed/notarized build is the normal
# release artifact, so its name stays short: ...-macos-arm64.dmg
ARCHIVE_SUFFIX="-unsigned"
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
            --notary-keychain)
                if [[ $# -lt 2 ]]; then
                    echo -e "${RED}❌ --notary-keychain requires a value${NC}"
                    exit 1
                fi
                NOTARY_KEYCHAIN="$2"
                shift 2
                ;;
            *)
                echo -e "${RED}❌ Unknown option: $1${NC}"
                echo "Usage: ./tools/build_macos.sh [--clean] [--sign-identity <identity>] [--notary-profile <profile>] [--notary-keychain <path>]"
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
        # qlmanage -s N caps the preview size, it does not scale the artwork
        # up. The source SVG declares width/height of 64, so QuickLook draws
        # it at 64px in the corner of a 1024px canvas and leaves the rest
        # transparent - which is exactly what a tiny top-left icon in Finder
        # looks like. Render from a copy that declares the target size so the
        # vector is rasterised at full resolution instead.
        local scaled_svg rendered_icon
        scaled_svg="$ICON_RENDER_DIR/icon-1024.svg"
        sed -E \
            -e '1,/<svg/ s/(<svg[^>]*[[:space:]])width="[^"]*"/\1width="1024"/' \
            -e '1,/<svg/ s/(<svg[^>]*[[:space:]])height="[^"]*"/\1height="1024"/' \
            "$ICON_VECTOR_SOURCE" > "$scaled_svg"

        rendered_icon="$ICON_RENDER_DIR/$(basename "$scaled_svg").png"
        qlmanage -t -s 1024 -o "$ICON_RENDER_DIR" "$scaled_svg" >/dev/null 2>&1
        if [[ -f "$rendered_icon" ]]; then
            # Normalise to an exact 1024x1024 square regardless of what
            # QuickLook produced.
            sips -z 1024 1024 "$rendered_icon" \
                --out "$ICON_MASTER_PNG" >/dev/null 2>&1
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
        --target-architecture="$TARGET_ARCH"
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

    # PyInstaller defaults the bundle version to 0.0.0, which is what
    # Finder and a signed/notarized release would report.
    local version
    version="$(tr -d ' \t\n\r' < "$PROJECT_ROOT/VERSION" 2>/dev/null)"
    version="${version#v}"
    if [[ -n "$version" ]]; then
        /usr/libexec/PlistBuddy -c \
            "Set :CFBundleShortVersionString $version" \
            "$APP_PATH/Contents/Info.plist" >/dev/null 2>&1 || true
        /usr/libexec/PlistBuddy -c \
            "Set :CFBundleVersion $version" \
            "$APP_PATH/Contents/Info.plist" >/dev/null 2>&1 \
            || /usr/libexec/PlistBuddy -c \
                "Add :CFBundleVersion string $version" \
                "$APP_PATH/Contents/Info.plist" >/dev/null 2>&1 || true
        echo -e "${GREEN}✅ Bundle version set to $version${NC}"
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
    /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string \"LM Studio Tray Manager\"" "$plist_path" 2>/dev/null || \
        /usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName \"LM Studio Tray Manager\"" "$plist_path"
    /usr/libexec/PlistBuddy -c "Add :CFBundleName string \"LM Studio Tray Manager\"" "$plist_path" 2>/dev/null || \
        /usr/libexec/PlistBuddy -c "Set :CFBundleName \"LM Studio Tray Manager\"" "$plist_path"

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
        # Editing Info.plist and copying resources both invalidate the
        # ad-hoc signature PyInstaller applied ("plist or signature have
        # been modified"). Re-seal so the unsigned build still verifies.
        codesign --force --deep --sign - "$APP_PATH" >/dev/null 2>&1 || true
        return
    fi

    echo -e "${BLUE}🔏 Code signing app bundle...${NC}"

    # A PyInstaller bundle needs Hardened Runtime exceptions; signing with
    # --options runtime alone produces an app that crashes on launch.
    local entitlements="$PROJECT_ROOT/tools/macos-entitlements.plist"
    local sign_args=(--force --deep --options runtime)
    if [[ -f "$entitlements" ]]; then
        sign_args+=(--entitlements "$entitlements")
    else
        echo -e "${RED}⚠️  $entitlements missing; signing without it${NC}"
    fi

    codesign "${sign_args[@]}" --sign "$SIGN_IDENTITY" "$APP_PATH"
    codesign --verify --deep --strict --verbose=2 "$APP_PATH"
    ARCHIVE_SUFFIX=""
    echo -e "${GREEN}✅ App bundle signed${NC}"
}

# Echo the credential arguments for notarytool, including --keychain when a
# dedicated keychain is configured or present at the default location.
notary_args() {
    printf '%s\n' --keychain-profile "$NOTARY_PROFILE"

    local keychain="$NOTARY_KEYCHAIN"
    if [[ -z "$keychain" && -f "$DEFAULT_NOTARY_KEYCHAIN" ]]; then
        keychain="$DEFAULT_NOTARY_KEYCHAIN"
    fi
    if [[ -n "$keychain" ]]; then
        printf '%s\n' --keychain "$keychain"
    fi
}

# Unlocking is best effort: a locked keychain fails mid-notarization, which
# is the worst moment for it.
unlock_notary_keychain() {
    local keychain="$NOTARY_KEYCHAIN"
    if [[ -z "$keychain" && -f "$DEFAULT_NOTARY_KEYCHAIN" ]]; then
        keychain="$DEFAULT_NOTARY_KEYCHAIN"
    fi
    [[ -n "$keychain" ]] || return 0

    if [[ -n "${NOTARY_KEYCHAIN_PASSWORD:-}" ]]; then
        security unlock-keychain -p "$NOTARY_KEYCHAIN_PASSWORD" "$keychain" \
            2>/dev/null || true
    fi
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

    unlock_notary_keychain
    local notary_opts=()
    while IFS= read -r line; do
        notary_opts+=("$line")
    done < <(notary_args)

    local notarize_zip="${BUILD_DIR}/LM-Studio-Tray-Manager-notarize.zip"
    rm -f "$notarize_zip"

    ditto -c -k --keepParent "$APP_PATH" "$notarize_zip"
    xcrun notarytool submit "$notarize_zip" "${notary_opts[@]}" --wait
    xcrun stapler staple "$APP_PATH"
    xcrun stapler validate "$APP_PATH"

    ARCHIVE_SUFFIX=""
    echo -e "${GREEN}✅ App bundle notarized and stapled${NC}"
}

create_release_archive() {
    echo -e "${BLUE}📦 Creating release archive...${NC}"

    VERSION=$(cat VERSION)
    mkdir -p "$RELEASE_DIR"

    # Drop macOS artifacts from earlier runs. The suffix encodes the signing
    # state, so a leftover "unsigned" file would otherwise sit next to the
    # signed one and be published by the release workflow's wildcard.
    rm -f "$RELEASE_DIR"/lmstudio-tray-manager-*-macos-*.tar.gz \
          "$RELEASE_DIR"/lmstudio-tray-manager-*-macos-*.dmg

    ARCHIVE_NAME="lmstudio-tray-manager-${VERSION}-macos-${TARGET_ARCH}${ARCHIVE_SUFFIX}.tar.gz"

    tar -czf "$RELEASE_DIR/$ARCHIVE_NAME" \
        -C "$DIST_DIR" \
        LM-Studio-Tray-Manager.app

    # Write checksums with relative filenames for portable verification.
    if command -v sha256sum >/dev/null 2>&1; then
        (cd "$RELEASE_DIR" && sha256sum "$ARCHIVE_NAME" > "SHA256SUMS-macos.txt")
    else
        (cd "$RELEASE_DIR" && shasum -a 256 "$ARCHIVE_NAME" > "SHA256SUMS-macos.txt")
    fi

    create_dmg "$VERSION"

    # Checksums cover every artifact, so regenerate after the DMG exists.
    if command -v sha256sum >/dev/null 2>&1; then
        (cd "$RELEASE_DIR" && sha256sum lmstudio-tray-manager-*-macos-* \
            > "SHA256SUMS-macos.txt")
    else
        (cd "$RELEASE_DIR" && shasum -a 256 lmstudio-tray-manager-*-macos-* \
            > "SHA256SUMS-macos.txt")
    fi

    echo -e "${GREEN}✅ Release artifacts created${NC}"
    echo ""
    ls -lh "$RELEASE_DIR"/lmstudio-tray-manager-*-macos-*
    echo ""
    echo "🔐 Checksums:"
    cat "$RELEASE_DIR/SHA256SUMS-macos.txt"
}

create_dmg() {
    local version="$1"
    local dmg_name="lmstudio-tray-manager-${version}-macos-${TARGET_ARCH}${ARCHIVE_SUFFIX}.dmg"
    local dmg_path="$RELEASE_DIR/$dmg_name"
    local staging="$BUILD_DIR/dmg"

    echo -e "${BLUE}💿 Creating DMG...${NC}"

    rm -rf "$staging" "$dmg_path"
    mkdir -p "$staging"
    cp -R "$APP_PATH" "$staging/"

    # Drag-and-drop target, so users install without a terminal.
    ln -s /Applications "$staging/Applications"

    if ! hdiutil create \
            -volname "LM Studio Tray Manager" \
            -srcfolder "$staging" \
            -ov -format UDZO \
            "$dmg_path" >/dev/null; then
        echo -e "${RED}❌ DMG creation failed${NC}"
        rm -rf "$staging"
        return 1
    fi
    rm -rf "$staging"

    # An unsigned DMG triggers Gatekeeper even when the app inside is
    # notarized, so sign and staple the container as well.
    if [[ -n "$SIGN_IDENTITY" ]]; then
        codesign --force --sign "$SIGN_IDENTITY" "$dmg_path"
        echo -e "${GREEN}✅ DMG signed${NC}"
    fi
    if [[ -n "$NOTARY_PROFILE" && -n "$SIGN_IDENTITY" ]]; then
        echo -e "${BLUE}🧾 Notarizing DMG...${NC}"
        unlock_notary_keychain
        local notary_opts=()
        while IFS= read -r line; do
            notary_opts+=("$line")
        done < <(notary_args)
        xcrun notarytool submit "$dmg_path" "${notary_opts[@]}" --wait
        xcrun stapler staple "$dmg_path"
        xcrun stapler validate "$dmg_path"
        echo -e "${GREEN}✅ DMG notarized and stapled${NC}"
    fi

    echo -e "${GREEN}✅ DMG created: $dmg_name${NC}"
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
