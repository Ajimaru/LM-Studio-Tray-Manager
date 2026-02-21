# Building Binary Distribution

This document describes how to build a standalone binary of LM Studio Tray Manager using PyInstaller.

## Overview

The binary build process creates a single executable file that bundles:

- Python interpreter
- All Python dependencies (PyGObject, etc.)
- GTK3 GObject Introspection bindings
- Application assets (icons, VERSION file, etc.)

## Quick Start

### Automated Build (Recommended)

```bash
chmod +x build.sh
./build.sh
```

This will:

1. Check dependencies
2. Create a Python 3.10 venv (if missing) with system site-packages
3. Clean previous builds
4. Run PyInstaller
5. Strip debug symbols
6. Compress with UPX
7. Show final binary size

### Manual Build

```bash
# Install build dependencies (pinned versions)
pip install -r requirements-build.txt

# Build using Python script
python3 build_binary.py

# Or build using spec file
pyinstaller lmstudio-tray-manager.spec
```

## Requirements

### Build Dependencies

```bash
# Ubuntu/Debian
sudo apt install python3.10 python3.10-venv python3-pip upx binutils

# Fedora
sudo dnf install python3-pip upx binutils

# Arch Linux
sudo pacman -S python-pip upx binutils
```

### Python Packages

```bash
pip install -r requirements-build.txt
```

## Build Methods

### Method 1: Shell Script (Easiest)

The `build.sh` script automates the entire process with optimization:

```bash
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
vim lmstudio-tray-manager.spec

# Build using spec
pyinstaller lmstudio-tray-manager.spec
```

**Customization options:**

- Hidden imports list
- Excluded modules
- Data files
- Build flags (strip, upx, console)

## Optimization

### Size Reduction

1. **Strip debug symbols** (saves ~5-10 MB):

   ```bash
   strip dist/lmstudio-tray-manager
   ```

2. **UPX compression** (saves ~50-70%):

   ```bash
   upx --best dist/lmstudio-tray-manager
   # Or for maximum compression (slower):
   upx --best --lzma dist/lmstudio-tray-manager
   ```

3. **Exclude unused modules** (edit spec file):

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
| + UPX | 15-25 MB |
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
- `gir1.2-ayatanaappindicator3-0.1`

Optional (silences a warning):

- `libcanberra-gtk3-module`

### Binary Crashes on Startup

**Error:** Segmentation fault or silent exit

**Solutions:**

1. Check GTK3 is installed on target system:

   ```bash
   sudo apt install gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
   ```

2. Run with debug output:

   ```bash
   ./dist/lmstudio-tray-manager 2>&1 | tee debug.log
   ```

3. Build without UPX compression:
   Edit spec file: `upx=False`

### Large Binary Size

**Issue:** Binary exceeds 50 MB

**Solutions:**

1. Enable strip: `strip=True` in spec file
2. Enable UPX: `upx=True` in spec file
3. Exclude unused modules (see Optimization section)
4. Use `--exclude-module` flag:

   ```bash
   pyinstaller --exclude-module tkinter lmstudio_tray.py
   ```

### UPX Not Working

**Error:** `upx: not found` or UPX compression fails

**Solutions:**

1. Install UPX:

   ```bash
   sudo apt install upx
   ```

2. Disable UPX in spec file if problematic:

   ```python
   upx=False
   ```

## Distribution

### Creating Release Package

```bash
# Create tarball
cd dist/
tar -czf lmstudio-tray-manager-$(cat ../VERSION)-linux-x86_64.tar.gz \
    lmstudio-tray-manager

# Create checksums
sha256sum lmstudio-tray-manager-*-linux-x86_64.tar.gz > \
    SHA256SUMS.txt
```

### Installation

Users can install the binary:

```bash
# Extract
tar -xzf lmstudio-tray-manager-*.tar.gz

# Move to system path
sudo mv lmstudio-tray-manager /usr/local/bin/

# Make executable
sudo chmod +x /usr/local/bin/lmstudio-tray-manager

# Run
lmstudio-tray-manager
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Build Binary

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y upx gir1.2-gtk-3.0
          pip install -r requirements.txt
          pip install -r requirements-build.txt
      
      - name: Build binary
        run: ./build.sh
      
      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: lmstudio-tray-manager
          path: dist/lmstudio-tray-manager
```

## Alternative Approaches

For smaller binaries or different requirements, consider:

### Nuitka

- Compiles Python to C
- Smaller binaries (~5-10 MB)
- Faster startup time
- More complex build process

### AppImage

- Standard Linux app format
- Includes all dependencies
- Larger size (~80-100 MB)
- Better compatibility

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
