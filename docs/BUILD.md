# Building Binary Distribution

This document describes how to build standalone releases of LM Studio Tray Manager.

**For most users and distributions, the [AppImage release](#appimage-recommended---fully-portable) is recommended.** It's fully self-contained with Python, GTK3, all dependencies, and the application bundled together—truly portable across all Linux distributions. No setup script or system dependencies needed. See [AppImage (Recommended)](#appimage-recommended---fully-portable) for details.

## Table of Contents

- [Building Binary Distribution](#building-binary-distribution)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
    - [AppImage (Recommended) - Fully Portable](#appimage-recommended---fully-portable)
    - [Binary (Build locally)](#binary-build-locally)
    - [macOS .app Bundle](#macos-app-bundle)
    - [Windows .exe and Installer](#windows-exe-and-installer)
  - [Quick Start](#quick-start)
    - [AppImage Build (Docker-based, Recommended)](#appimage-build-docker-based-recommended)
    - [Automated Binary Build (Local)](#automated-binary-build-local)
    - [macOS .app Build (Local)](#macos-app-build-local)
    - [Manual Binary Build](#manual-binary-build)
    - [Docker AppImage Build (Alternative)](#docker-appimage-build-alternative)
  - [Requirements](#requirements)
    - [Build Dependencies](#build-dependencies)
    - [Python Packages](#python-packages)
  - [Build Methods](#build-methods)
    - [Method 1: Shell Script (Easiest)](#method-1-shell-script-easiest)
    - [Method 2: Python Script](#method-2-python-script)
    - [Method 3: PyInstaller Spec File](#method-3-pyinstaller-spec-file)
  - [macOS Build Details](#macos-build-details)
    - [Build Script](#build-script)
    - [Local Testing](#local-testing)
    - [Release Artifacts](#release-artifacts)
    - [Code Signing and Notarization](#code-signing-and-notarization)
  - [Windows Build Details](#windows-build-details)
    - [Build script (Windows)](#build-script-windows)
    - [Requirements (Windows build)](#requirements-windows-build)
    - [Release artifacts (Windows)](#release-artifacts-windows)
    - [Console output from a windowed build](#console-output-from-a-windowed-build)
    - [Code signing (Windows)](#code-signing-windows)
    - [GitHub Actions Windows release](#github-actions-windows-release)
  - [Optimization](#optimization)
    - [Size Reduction](#size-reduction)
    - [Expected Sizes](#expected-sizes)
  - [Testing](#testing)
    - [Basic Tests](#basic-tests)
    - [Full Test](#full-test)
  - [Troubleshooting](#troubleshooting)
    - [Missing GTK3 Libraries](#missing-gtk3-libraries)
    - [Runtime Requirements on Target Machine](#runtime-requirements-on-target-machine)
    - [Binary Crashes on Startup](#binary-crashes-on-startup)
    - [Large Binary Size](#large-binary-size)
  - [Alternative Approaches](#alternative-approaches)
    - [Nuitka](#nuitka)
    - [AppImage (Recommended) - Fully Portable Release](#appimage-recommended---fully-portable-release)
      - [Option 1: Docker (Recommended)](#option-1-docker-recommended)
      - [Option 2: GitHub Actions (Automatic)](#option-2-github-actions-automatic)
    - [Rust Rewrite](#rust-rewrite)
  - [Support](#support)
  - [Next Steps](#next-steps)

## Overview

The project offers multiple build approaches with different portability levels:

### AppImage (Recommended) - Fully Portable

The AppImage release is the **most portable and recommended option** for Linux:

- ✅ Bundles everything: Python, GTK3, GObject-Introspection, all libraries
- ✅ Single executable file (~34 MB)
- ✅ Works on virtually any modern Linux system
- ✅ No setup script or system dependencies needed
- ✅ Just `chmod +x` and run

**Build method:** `tools/Dockerfile.release` (Docker-based, recommended)

### Binary (Build locally)

For custom Linux builds on your machine:

- Python interpreter
- All Python application code and PyGObject
- Application assets (icons, VERSION file, etc.)

**Note:** GTK3 and GObject Introspection (GI) shared libraries must be installed on the target system at runtime.

### macOS .app Bundle

Native macOS application bundle built with PyInstaller:

- ✅ Self-contained .app directory structure
- ✅ Includes Python 3.12 runtime and all dependencies
- ✅ Bundles rumps library (macOS tray integration)
- ✅ Bundles PyObjC (`objc`, `Foundation`), used to run AppKit calls on the
  main thread - without it menu updates from worker threads crash the app
- ✅ ~50-80 MB uncompressed, ~30 MB as tar.gz
- ✅ Works on macOS 12+
- Optional: Code Sign + Notarize for Gatekeeper approval

**Build method:** `./tools/build_macos.sh` (local) or GitHub Actions `build-macos` job (CI/CD)

### Windows .exe and Installer

Native Windows build produced with PyInstaller:

- ✅ Single self-contained `.exe`, no Python installation needed
- ✅ Bundles pystray (notification-area icon) and Pillow
- ✅ Bundles tkinter for the status, about and configuration dialogs
- ✅ ~17 MB as a one-file build, ~19 MB as an installer
- ✅ Works on Windows 10 and 11 (x64)
- ❌ Not code-signed: SmartScreen warns on first run

**Build method:** `.\tools\build_windows.ps1` (local) or GitHub Actions `build-windows` job (CI/CD)

## Quick Start

### AppImage Build (Docker-based, Recommended)

For a fully portable AppImage with all dependencies bundled:

```bash
docker build -f tools/Dockerfile.release -t lmstudio-release:latest .
```

This produces a 34 MB AppImage with:

- Python 3.12
- GTK3 runtime + all required libraries
- GObject-Introspection + typelibs
- Application code and assets

**GitHub Actions:** The `release.yml` workflow automatically uses this method when you push a version tag.

### Automated Binary Build (Local)

```bash
chmod +x tools/build.sh
./tools/build.sh
```

This will:

1. Check dependencies
2. Create a Python venv (if missing) with system site-packages
3. Clean previous builds
4. Run PyInstaller
5. Strip debug symbols
6. Show final binary size

### macOS .app Build (Local)

For building a native macOS .app bundle on your Mac:

```bash
chmod +x tools/build_macos.sh
./tools/build_macos.sh
```

For a signed build:

```bash
./tools/build_macos.sh --clean --sign-identity "Developer ID Application: Your Name (TEAMID)"
```

For a signed and notarized build using a stored notarytool profile:

```bash
./tools/build_macos.sh \
  --clean \
  --sign-identity "Developer ID Application: Your Name (TEAMID)" \
  --notary-profile AC_NOTARY
```

### Storing notary credentials that survive

`notarytool store-credentials` writes to the iCloud-managed "Local Items"
keychain unless told otherwise, and the profile can vanish between runs
("No Keychain password item found"). Use a dedicated keychain instead:

```bash
security create-keychain -p "PASSWORD" ~/Library/Keychains/notary.keychain-db
security set-keychain-settings ~/Library/Keychains/notary.keychain-db
security unlock-keychain -p "PASSWORD" ~/Library/Keychains/notary.keychain-db

xcrun notarytool store-credentials "AC_NOTARY" \
  --keychain ~/Library/Keychains/notary.keychain-db \
  --apple-id "you@example.com" \
  --team-id "TEAMID" \
  --password "xxxx-xxxx-xxxx-xxxx"
```

`set-keychain-settings` without `-t` disables the idle lock, which would
otherwise trip mid-notarization. The build script picks up
`~/Library/Keychains/notary.keychain-db` automatically; pass
`--notary-keychain <path>` for a different location, and export
`NOTARY_KEYCHAIN_PASSWORD` to have the script unlock it.

Notarization polls Apple for several minutes. If the Mac sleeps the
connection drops ("The Internet connection appears to be offline") and the
ticket is never stapled, so wrap long runs:

```bash
caffeinate -is ./tools/build_macos.sh --clean \
  --sign-identity "Developer ID Application: Your Name (TEAMID)" \
  --notary-profile AC_NOTARY
```

This will:

1. Check for Python 3 and Xcode Command Line Tools
2. Render a high-resolution ICNS icon from the SVG asset when available
3. Create a Python venv with rumps (macOS tray library)
4. Install all build dependencies
5. Build a native Apple Silicon `.app` bundle with PyInstaller
6. Bundle application resources and menu bar metadata
7. Optionally code sign and notarize the app
8. Create a `.tar.gz` release archive with checksums

**Output:**

- **App bundle:** `dist/LM-Studio-Tray-Manager.app`
- **Release archive:** `release/lmstudio-tray-manager-vX.Y.Z-macos-arm64.tar.gz`
  (an `-unsigned` suffix is added when no signing identity is passed)
- **Checksums:** `release/SHA256SUMS-macos.txt`

**Test the app:**

```bash
# From terminal
dist/LM-Studio-Tray-Manager.app/Contents/MacOS/LM-Studio-Tray-Manager

# Or from Finder
open dist/LM-Studio-Tray-Manager.app --args --auto-start-daemon
```

**Clean build:**

```bash
./tools/build_macos.sh --clean
```

### Manual Binary Build

```bash
# Install build dependencies (pinned versions)
pip install -r requirements-build.txt

# Build using Python script
python3 tools/build_binary.py

# Or build using spec file
pyinstaller lmstudio-tray-manager.spec
```

### Docker AppImage Build (Alternative)

For Windows/macOS developers without native Linux, use Docker:

```bash
docker build -f tools/Dockerfile.release -t lmstudio-release:latest .
docker create --name release-temp lmstudio-release:latest
docker cp release-temp:/app/dist dist/
docker rm release-temp
```

## Requirements

### Build Dependencies

A C toolchain (gcc or clang) is required because the PyInstaller
bootloader gets compiled during installation.  The bootloader also links
against **zlib**; you must have the zlib development headers/libraries
installed (`zlib1g-dev` on Debian/Ubuntu, `zlib-devel` on Fedora).
On Debian/Ubuntu the required build packages are provided by
`build-essential` plus `zlib1g-dev`; Fedora ships `@development-tools` and
`zlib-devel`.

```bash
# Ubuntu/Debian
sudo apt install python3.12 python3.12-venv python3-pip binutils build-essential zlib1g-dev

# Fedora
sudo dnf install python3-pip binutils @development-tools zlib-devel

# Arch Linux
sudo pacman -S python-pip binutils base-devel zlib
```

The `tools/build.sh` helper script now checks for a working compiler; if none is
found it will prompt you and (optionally) attempt to install the necessary
packages before continuing.

### Python Packages

```bash
pip install -r requirements-build.txt
```

> **Note:** the repository also contains a companion
> [`requirements.txt`](../requirements.txt) file. That copy omits the
> ``--hash=`` pins and line continuations so that dependency scanners
> (Depfu, Snyk, etc.) can read it without errors. The actual build
> process continues to rely on ``requirements-build.txt`` for
> integrity‑checked installs.

## Build Methods

### Method 1: Shell Script (Easiest)

The `tools/build.sh` script automates the entire process with optimization:

```bash
chmod +x tools/build.sh
./tools/build.sh
```

**Output:**

- Binary: `dist/lmstudio-tray-manager`
- Size: ~15-25 MB (optimized) or ~40-50 MB (unoptimized)

Notes:

- `tools/build.sh` creates a `venv` automatically when missing.
- The venv uses `--system-site-packages` so `gi` bindings are available.

### Method 2: Python Script

The `tools/build_binary.py` script provides programmatic build control:

```bash
python3 tools/build_binary.py
```

**Features:**

- Dependency checking
- Hidden imports auto-detection
- Data files bundling
- Build status reporting

### Method 3: PyInstaller Spec File

For advanced customization, edit `lmstudio-tray-manager.spec`:

```bash
# Edit spec file
nano lmstudio-tray-manager.spec

# Build using spec
pyinstaller lmstudio-tray-manager.spec
```

**Customization options:**

- Hidden imports list
- Excluded modules
- Data files
- Build flags (strip, console)

## macOS Build Details

### Build Script

The `tools/build_macos.sh` script is the easiest way to build for macOS:

**Features:**

- Automatic Python 3 and Xcode Command Line Tools detection
- Uses macOS Quick Look to rasterize the SVG icon into a 1024px master image
- Creates isolated venv with rumps library
- PyInstaller with macOS-specific options:
  - `--windowed --onedir` to emit a real `.app` bundle
  - `--target-architecture` follows `uname -m`; override with `TARGET_ARCH`
  - Bundle identifier: `com.lmstudio.tray-manager`
  - Automatic ICNS generation from `assets/img/lm-studio-tray-manager.svg`
- Resource bundling (setup.sh, README.md, LICENSE, assets)
- Optional code signing and notarization in the same build flow
- Automatic .tar.gz archive creation with checksums

### Local Testing

Test the unsigned app directly:

```bash
# Start the app from command line
dist/LM-Studio-Tray-Manager.app/Contents/MacOS/LM-Studio-Tray-Manager

# Or with options
dist/LM-Studio-Tray-Manager.app/Contents/MacOS/LM-Studio-Tray-Manager --debug

# Or from Finder
open dist/LM-Studio-Tray-Manager.app

# Or with auto-start daemon
open dist/LM-Studio-Tray-Manager.app --args --auto-start-daemon
```

**Verify:**

- Menu bar icon appears in top-right corner
- `lms ps` shows daemon status
- Click menu bar icon to see tray menu and options

### Release Artifacts

After building, release artifacts are created in the `release/` directory:

- **Archive:** `lmstudio-tray-manager-vX.Y.Z-macos-arm64-unsigned.tar.gz`
  (signed builds drop the suffix: `...-macos-arm64.tar.gz`)
- **Checksums:** `SHA256SUMS-macos.txt`

These can be distributed directly or uploaded to GitHub Releases.

### Code Signing and Notarization

For distribution beyond testing, sign the `.app` and notarize it.

1. **Obtain Developer ID Certificate**
   - Enroll in [Apple Developer Program](https://developer.apple.com/programs/)
   - Create a Developer ID Application certificate

Store notarization credentials once:

```bash
xcrun notarytool store-credentials AC_NOTARY \
  --apple-id "you@example.com" \
  --team-id "TEAM1234567" \
  --password "app-specific-password"
```

2. **Build, sign, and notarize in one command**

```bash
./tools/build_macos.sh \
  --clean \
  --sign-identity "Developer ID Application: Your Name (TEAM1234567)" \
  --notary-profile AC_NOTARY
```

3. **Verify the stapled result**

```bash
xcrun stapler validate dist/LM-Studio-Tray-Manager.app
```

### GitHub Actions macOS Release

The `build-macos` job in `.github/workflows/release.yml` now calls `tools/build_macos.sh` directly.

If the following secrets are present, the workflow imports your Developer ID certificate, signs the bundle, stores notarytool credentials, notarizes the build, and uploads a notarized archive:

- `MACOS_CERTIFICATE_BASE64`
- `MACOS_CERTIFICATE_PASSWORD`
- `MACOS_KEYCHAIN_PASSWORD` (optional)
- `APPLE_ID`
- `APPLE_TEAM_ID`
- `APPLE_APP_PASSWORD`

If those secrets are not configured, the same workflow still produces an unsigned macOS archive for testing.

See [macOS Code Signing Guide](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution) for detailed instructions.

## Windows Build Details

### Build script (Windows)

`tools/build_windows.ps1` is the counterpart to `tools/build_macos.sh`:

**Features:**

- Verifies the Python interpreter actually runs before using it - Windows 11
  ships an App Execution Alias at
  `%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe` that is on `PATH` even
  when Python is not installed, and only opens the Microsoft Store
- Creates an isolated venv, installs `requirements-build.txt` with
  `--require-hashes` and `requirements-windows.txt` pinned
- Generates a multi-resolution `.ico` from `assets/img/lm-studio-tray-manager.png`
  with Pillow, so no binary icon is committed
- Runs `tools/build_binary.py`, which on Windows adds `pystray._win32`,
  `PIL._tkinter_finder` and `tkinter` as hidden imports and skips the
  pkg-config GdkPixbuf lookup
- Smoke-tests the executable, packages the portable ZIP, builds the Inno
  Setup installer, and writes `SHA256SUMS-windows.txt`

```powershell
# Full build (installer included when Inno Setup is present)
.\tools\build_windows.ps1

# Clean rebuild
.\tools\build_windows.ps1 -Clean

# Portable ZIP only
.\tools\build_windows.ps1 -SkipInstaller
```

### Requirements (Windows build)

- Windows 10 or 11, x64
- Python 3.10+ from [python.org](https://www.python.org/downloads/) (the
  Microsoft Store build works too, but the alias caveat above applies)
- Inno Setup 6, only for the installer:

```powershell
winget install JRSoftware.InnoSetup
```

The build script finds `ISCC.exe` under `%LOCALAPPDATA%\Programs\Inno Setup 6`
as well as both `Program Files` locations — winget installs per-user unless it
is run elevated. Without Inno Setup the build still succeeds and simply skips
the installer.

### Release artifacts (Windows)

| Artifact | Contents |
| --- | --- |
| `lmstudio-tray-manager-X.Y.Z-windows-x86_64.exe` (in `dist\`) | The one-file build, ~17 MB |
| `lmstudio-tray-manager-X.Y.Z-windows-x86_64.zip` | Portable: the `.exe`, `lmstudio_autostart.ps1`, `VERSION`, `AUTHORS`, `LICENSE`, `README.md` |
| `lmstudio-tray-manager-X.Y.Z-windows-x86_64-setup.exe` | Inno Setup installer, ~19 MB |
| `SHA256SUMS-windows.txt` | Checksums, in `sha256sum -c` format |

### Console output from a windowed build

The executable is built with `--windowed`, so it starts without a console and
`sys.stdout`/`sys.stderr` are `None`. The app reattaches the calling
terminal's console when there is one, so `--version` and `--help` print
normally from PowerShell, and falls back to the null device otherwise —
argparse writes to `stderr` unconditionally and would otherwise raise.

One consequence when scripting against it: PowerShell does not wait for a
GUI-subsystem process, so `$LASTEXITCODE` is never set. Use `Start-Process`
to get a real exit code:

```powershell
$p = Start-Process .\dist\lmstudio-tray-manager.exe -ArgumentList '--version' `
    -Wait -PassThru -NoNewWindow
$p.ExitCode
```

### Code signing (Windows)

The Windows artifacts are **not signed** — the project has no Authenticode
certificate, so SmartScreen warns on first run. This is the one place the
Windows release is weaker than the macOS one, which is signed and notarized.
Users verify against `SHA256SUMS-windows.txt` instead.

### GitHub Actions Windows release

The `build-windows` job in `.github/workflows/release.yml` runs on
`windows-latest`, installs Inno Setup via winget, runs
`tools/build_windows.ps1 -Clean`, insists that all three artifacts exist, and
uploads them to the release on a tag push.

## Optimization

### Size Reduction

1. **Strip debug symbols** (saves ~5-10 MB):

   ```bash
   strip dist/lmstudio-tray-manager
   ```

2. **Exclude unused modules** (edit spec file):

   ```python
   excludes=[
       'tkinter',
       'matplotlib',
       'numpy',
       'pandas',
   ]
   ```

### Expected Sizes

| Build Type | Size |
| ---------- | ---- |
| Unoptimized | 40-50 MB |
| + Strip | 30-40 MB |
| + Excludes | 10-20 MB |

## Testing

### Basic Tests

```bash
# Version check
./dist/lmstudio-tray-manager --version

# Help message
./dist/lmstudio-tray-manager --help

# Run application
./dist/lmstudio-tray-manager

# Auto-start daemon on launch
./dist/lmstudio-tray-manager --auto-start-daemon

# Start GUI on launch (stops daemon first)
./dist/lmstudio-tray-manager --gui

# Debug mode
./dist/lmstudio-tray-manager --debug
```

### Full Test

The project uses `pytest` with the [pytest-cov](https://pypi.org/project/pytest-cov/)
plugin to generate coverage reports.  On Debian/Ubuntu you can install the
required packages with:

```bash
sudo apt install python3-pytest python3-pytest-cov
# or, if you prefer pip:
# pip install pytest pytest-cov
```

```bash
# Run all tests with coverage
pytest tests/ --cov=lmstudio_tray --cov=build_binary --cov-report=term-missing

# Test binary execution
./dist/lmstudio-tray-manager &
sleep 5
pkill -f lmstudio-tray-manager
```

## Troubleshooting

### Missing GTK3 Libraries

**Error:** `gi.repository.Gtk not found`

**Solution:** Add hidden imports to spec file:

```python
hiddenimports=[
    'gi.repository.Gtk',
    'gi.repository.GLib',
    # ... other GTK modules
]
```

### Runtime Requirements on Target Machine

The binary still relies on system GTK/gi packages:

- `gir1.2-gtk-3.0`
- `gir1.2-ayatanaappindicator3-0.1` (provides GTK3 AppIndicator3
  namespace; some platforms may instead offer only `AppIndicator3`)

Optional (silences a warning):

- `libcanberra-gtk3-module`

### Binary Crashes on Startup

**Error:** Segmentation fault or silent exit

**Solutions:**

1. Check GTK3 is installed on target system:

   ```bash
   # example for Debian/Ubuntu
   sudo apt install gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
   ```

2. Run with debug output:

   ```bash
   ./dist/lmstudio-tray-manager 2>&1 | tee debug.log
   ```

3. Check `debug.log` for missing libraries or other errors.

### Large Binary Size

**Issue:** Binary exceeds 50 MB

**Solutions:**

1. Enable strip: `strip=True` in spec file
2. Exclude unused modules (see Optimization section)
3. Use `--exclude-module` flag:

   ```bash
   pyinstaller --exclude-module tkinter lmstudio_tray.py
   ```

## Alternative Approaches

For smaller binaries or different requirements, consider:

### Nuitka

- Compiles Python to C
- Smaller binaries (~5-10 MB)
- Faster startup time
- More complex build process

### AppImage (Recommended) - Fully Portable Release

**What is it?**

The AppImage is the **standard Linux application format** - truly portable across all distributions:

- Standard Linux app format recognized by most desktop environments
- Complete runtime environment bundled: Python, GTK3, GObject-Introspection, all libraries
- Single executable file that's completely self-contained
- Just ~34 MB with all dependencies included
- **Zero external dependencies** (except LM Studio daemon itself)

**How is it different from Binary Release?**

| Aspect | Binary Release | AppImage |
| --- | --- | --- |
| Python | ✓ Bundled | ✓ Bundled |
| PyGObject | ✓ Bundled | ✓ Bundled |
| GTK3 Runtime | ✗ System dep | ✓ Bundled |
| GI Typelibs | ✗ System dep | ✓ Bundled |
| Size | 15-25 MB | 34 MB |
| Setup needed | Yes (setup.sh) | No |
| Portability | Medium | **Excellent** |

**Key advantages:**

- ✓ Works on virtually any Linux distribution (2022+)
- ✓ No `setup.sh` needed - just `chmod +x` and run
- ✓ Better for distribution to end users
- ✓ Self-contained: LM Studio daemon is the *only* external requirement
- ✓ Works on systems where GTK3 isn't installed

**Building AppImage:**

#### Option 1: Docker (Recommended)

```bash
# Build AppImage using tools/Dockerfile.release
docker build -f tools/Dockerfile.release -t lmstudio-release:latest .

# Extract artifacts
CONTAINER_ID=$(docker create lmstudio-release:latest)
docker cp "$CONTAINER_ID":/app/dist/. dist/
docker rm "$CONTAINER_ID"

# Result: 34 MB AppImage with all dependencies
ls -lh dist/*.AppImage
```

#### Option 2: GitHub Actions (Automatic)

The `release.yml` workflow automatically builds AppImage using `tools/Dockerfile.release` when you push a version tag:

```bash
git tag v0.6.1
git push origin v0.6.1
# → release.yml builds AppImage automatically
```

**Using AppImage:**

```bash
chmod +x lmstudio-tray-manager-*.AppImage
./lmstudio-tray-manager-*.AppImage --auto-start-daemon
```

**Linux Compatibility:**

The AppImage works on most modern Linux systems with glibc ≥ 2.35 (released 2022):

| Distribution | Version | Status | glibc |
| --- | --- | --- | --- |
| Ubuntu | 24.04, 23.10, 22.04 LTS | ✅ Full | ≥ 2.35 |
| Debian | 12 (Bookworm), 11+ | ✅ Full | ≥ 2.36 |
| Fedora | 39+ | ✅ Full | ≥ 2.38 |
| openSUSE Leap | 15.5+ | ✅ Full | ≥ 2.35 |
| Linux Mint | 21.x+ | ✅ Full | ≥ 2.35 |
| Pop!_OS | 22.04+ | ✅ Full | ≥ 2.35 |
| **Older systems** | < 2022 | ⚠️ May not work | < 2.35 |

**For older Linux systems:** Use the source tarball with Python package release instead.

**Note:** Chromium-based AppImages occasionally fail to start due to an
incorrectly configured SUID sandbox helper. The tray manager
automatically launches AppImages with `--no-sandbox` to work around this
issue; otherwise you may need to run the AppImage manually with that flag.

### Rust Rewrite

- Native binary (~2-5 MB)
- Maximum performance
- Requires full rewrite
- Uses gtk-rs bindings

See [GitHub Discussions](https://github.com/Ajimaru/LM-Studio-Tray-Manager/discussions) for more details on alternative approaches.

## Support

For build issues or questions:

- [Open an issue](https://github.com/Ajimaru/LM-Studio-Tray-Manager/issues)
- [Discussions](https://github.com/Ajimaru/LM-Studio-Tray-Manager/discussions)
- Check existing issues with `build` label

## Next Steps

After building the binary, proceed to [SETUP.md](SETUP.md) to configure and install it.
