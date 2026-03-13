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
    - [Code Signing (Optional)](#code-signing-optional)
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

**Build method:** `Dockerfile.release` (Docker-based, recommended)

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
- ✅ ~50-80 MB uncompressed, ~30 MB as tar.gz
- ✅ Works on macOS 12+
- Optional: Code Sign + Notarize for Gatekeeper approval

**Build method:** `./build_macos.sh` (local) or GitHub Actions `build-macos` job (CI/CD)

## Quick Start

### AppImage Build (Docker-based, Recommended)

For a fully portable AppImage with all dependencies bundled:

```bash
docker build -f Dockerfile.release -t lmstudio-release:latest .
```

This produces a 34 MB AppImage with:

- Python 3.12
- GTK3 runtime + all required libraries
- GObject-Introspection + typelibs
- Application code and assets

**GitHub Actions:** The `release.yml` workflow automatically uses this method when you push a version tag.

### Automated Binary Build (Local)

```bash
chmod +x build.sh
./build.sh
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
chmod +x build_macos.sh
./build_macos.sh
```

This will:

1. Check for Python 3 and Xcode Command Line Tools
2. Create a Python venv with rumps (macOS tray library)
3. Install all build dependencies
4. Build with PyInstaller for macOS (.onedir format)
5. Bundle application resources
6. Create a .tar.gz release archive with checksums

**Output:**

- **App bundle:** `dist/LM-Studio-Tray-Manager.app`
- **Release archive:** `release/lmstudio-tray-manager-vX.Y.Z-macos-unsigned.tar.gz`
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
./build_macos.sh --clean
```

### Manual Binary Build

```bash
# Install build dependencies (pinned versions)
pip install -r requirements-build.txt

# Build using Python script
python3 build_binary.py

# Or build using spec file
pyinstaller lmstudio-tray-manager.spec
```

### Docker AppImage Build (Alternative)

For Windows/macOS developers without native Linux, use Docker:

```bash
docker build -f Dockerfile.release -t lmstudio-release:latest .
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

The `build.sh` helper script now checks for a working compiler; if none is
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

The `build.sh` script automates the entire process with optimization:

```bash
chmod +x build.sh
./build.sh
```

**Output:**

- Binary: `dist/lmstudio-tray-manager`
- Size: ~15-25 MB (optimized) or ~40-50 MB (unoptimized)

Notes:

- `build.sh` creates a `venv` automatically when missing.
- The venv uses `--system-site-packages` so `gi` bindings are available.

### Method 2: Python Script

The `build_binary.py` script provides programmatic build control:

```bash
python3 build_binary.py
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

The `build_macos.sh` script is the easiest way to build for macOS:

**Features:**

- Automatic Python 3 and Xcode Command Line Tools detection
- Creates isolated venv with rumps library
- PyInstaller with macOS-specific options:
  - `--onedir` format (better for bundling resources)
  - Bundle identifier: `com.lmstudio.tray-manager`
  - Automatic icon detection from `assets/img/`
- Resource bundling (setup.sh, README.md, LICENSE, assets)
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

- **Archive:** `lmstudio-tray-manager-vX.Y.Z-macos-unsigned.tar.gz`
- **Checksums:** `SHA256SUMS-macos.txt`

These can be distributed directly or uploaded to GitHub Releases.

### Code Signing (Optional)

For distribution beyond testing, code signing is recommended:

1. **Obtain Developer ID Certificate**
   - Enroll in [Apple Developer Program](https://developer.apple.com/programs/)
   - Create a Developer ID Application certificate

2. **Sign the .app bundle**

   ```bash
   codesign --force --deep --options runtime \
     --sign "Developer ID Application: Your Name (TEAM1234567)" \
     dist/LM-Studio-Tray-Manager.app
   ```

3. **Notarize for Gatekeeper**

   ```bash
   xcrun notarytool submit lmstudio-tray-manager-vX.Y.Z-macos.zip \
     --keychain-profile "AC_NOTARY" \
     --wait
   ```

See [macOS Code Signing Guide](https://developer.apple.com/documentation/security/notarizing_macos_software_before_distribution) for detailed instructions.

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
# Build AppImage using Dockerfile.release
docker build -f Dockerfile.release -t lmstudio-release:latest .

# Extract artifacts
CONTAINER_ID=$(docker create lmstudio-release:latest)
docker cp "$CONTAINER_ID":/app/dist/. dist/
docker rm "$CONTAINER_ID"

# Result: 34 MB AppImage with all dependencies
ls -lh dist/*.AppImage
```

#### Option 2: GitHub Actions (Automatic)

The `release.yml` workflow automatically builds AppImage using `Dockerfile.release` when you push a version tag:

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
