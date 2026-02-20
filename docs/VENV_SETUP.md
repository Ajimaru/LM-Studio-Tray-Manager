# Virtual Environment Setup

The `setup.sh` script automates the complete setup process for LM Studio automation.

## Table of Contents

- [What setup.sh Does](#what-setupsh-does)
- [Quick Start](#quick-start)
- [Setup Script Outputs](#setup-script-outputs)
  - [If LM Studio Daemon is Missing](#if-lm-studio-daemon-is-missing)
  - [If LM Studio Desktop App is Missing](#if-lm-studio-desktop-app-is-missing)
  - [If Python 3.10 is Missing](#if-python-310-is-missing)
- [What's Inside the venv?](#whats-inside-the-venv)
- [File Structure After Setup](#file-structure-after-setup)
- [Environment Variables](#environment-variables)
- [Troubleshooting](#troubleshooting)
  - [venv not found](#venv-not-found)
  - [Checking Logs](#checking-logs)
- [PyGObject Import Errors](#pygobject-import-errors)
- [System Tray Icon Not Appearing](#system-tray-icon-not-appearing)
- [Why Python 3.10?](#why-python-310)
- [Python 3.12+ Support](#python-312-support)
  - [Option 1: Install Build Tools](#option-1-install-build-tools-not-recommended)
  - [Option 2: Wait for Debian/Ubuntu Packages](#option-2-wait-for-debianubuntu-packages)
  - [Option 3: Use Docker](#option-3-use-docker-alternative)
  - [Our Solution: Python 3.10 venv](#our-solution-python-310-venv)

## What setup.sh Does

The setup script checks for and optionally installs:

1. **LM Studio Daemon (llmster)** – Headless backend for model inference
   - Checks if `lms` CLI is available
   - If not found: Opens download page and asks to install

2. **LM Studio Desktop App** – GUI for model management
   - Intelligently detects .deb package installation
   - Searches for AppImage in: script directory, $HOME/Apps, $HOME/LM_Studio, $HOME/Applications, $HOME/.local/bin, /opt/lm-studio
   - Auto-detects both standard and versioned AppImage formats (e.g., LM-Studio-0.4.3-*.AppImage)
   - Allows manual AppImage path input
   - Optional (only needed for `--gui` option)

3. **Python 3.10** – Required for PyGObject/GTK3 compatibility
   - Checks for availability
   - Installs automatically if missing (via `apt`)

4. **Python Virtual Environment** – Isolated Python environment
   - Creates venv with system site-packages
   - Enables GTK3 introspection and PyGObject

## Quick Start

```bash
# Run the setup script (handles all checks and installations)
./setup.sh

# The setup will:
# ✓ Check for LM Studio daemon
# ✓ Check for LM Studio desktop app
# ✓ Install Python 3.10 if needed
# ✓ Create venv in ./venv/

# After setup, run the automation script
./lmstudio_autostart.sh

# Check logs in .logs directory
tail -f .logs/lmstudio_autostart.log

```

## Setup Script Outputs

### If LM Studio Daemon is Missing

```text
⚠ LM Studio daemon not found
  The daemon (llmster) is required for the automation scripts.
  
  Would you like to download LM Studio daemon? [y/n]:

```

Selecting `y` opens the download page. You'll need to install it manually from <https://lmstudio.ai/download>

### If LM Studio Desktop App is Missing

```text
⚠ LM Studio desktop app not found
  The desktop app is required for the --gui option.
  
  Choose installation method:
    1) Install .deb package (recommended for Ubuntu/Debian)
    2) Use AppImage (manual download)
    3) Skip (can be installed later)

```

**Option 1**: Download .deb from <https://lmstudio.ai/download> and install:

```bash
sudo apt install ./LM-Studio.deb

```

**Option 2**: Provide path to AppImage file:

```text
Enter path to AppImage file (or directory containing it): /home/user/Downloads/LM-Studio.AppImage

```

### If Python 3.10 is Missing

```text
⚠ Python 3.10 not found
  Python 3.10 is required for PyGObject/GTK3 compatibility.
  
  Would you like to install Python 3.10? [y/n]:

```

Selecting `y` installs Python 3.10 via `apt` (requires sudo password).

## What's Inside the venv?

- **Python 3.10** (optimized for PyGObject binary compatibility)
- **System site-packages** enabled (includes GTK3 introspection data)
- **Isolated environment** (pip packages don't conflict with system Python)
- **Full PyGObject + GTK3 support** for system tray functionality

## File Structure After Setup

After running `./setup.sh`, your project directory will contain:

```files
.
├── venv/                       # 🆕 Python virtual environment
├── .logs/                      # 📝 Log files directory
│   ├── setup.log               # Setup script log (created during setup)
│   ├── lmstudio_autostart.log  # Daemon script log
│   └── lmstudio_tray.log       # Tray monitor log
```

## Environment Variables

The setup is automatic, but you can customize with environment variables:

```bash
# Manually set venv location (if not in default ./venv)
export VENV_DIR=/custom/path/to/venv
./lmstudio_autostart.sh

# Enable debug mode
export LM_AUTOSTART_DEBUG=1
./lmstudio_autostart.sh

# Set model selection timeout (seconds)
export LM_AUTOSTART_SELECT_TIMEOUT=60
./lmstudio_autostart.sh -L  # Interactive model selection

```

## Troubleshooting

### venv not found

If the autostart script doesn't find your venv:

```bash
# Set VENV_DIR explicitly (or add to .bashrc/.zshrc)
export VENV_DIR=$(pwd)/venv
./lmstudio_autostart.sh

```

Or use it directly:

```bash
source ./venv/bin/activate
python3 ./lmstudio_tray.py

```

### Checking Logs

All output is logged to the `.logs/` directory:

```bash
# View setup logs (complete installation history)
cat .logs/setup.log

# View autostart daemon logs
tail -f .logs/lmstudio_autostart.log

# View tray monitor logs
tail -f .logs/lmstudio_tray.log

# Search for errors in all logs
grep -i 'error' .logs/*.log

# View all logs in real-time (in separate terminal)
tail -f .logs/*.log
```

### View tray monitor logs

tail -f .logs/lmstudio_tray.log

### View both in real-time (in separate terminals)

tail -f .logs/*.log

## PyGObject Import Errors

If you see `ImportError: cannot import name '_gi'`:

1. Verify Python 3.10 is being used:

   ```bash
   ./venv/bin/python3 --version

   ```

2. Check that system site-packages are enabled:

   ```bash
   ./venv/bin/python3 -c "import sys; print(sys.prefix, sys.base_prefix)"

   ```

3. Reinstall the venv:

   ```bash
   rm -rf venv/
   ./setup.sh

   ```

## System Tray Icon Not Appearing

If the tray monitor is running but icon not visible:

1. Check if the daemon is really running:

   ```bash
   lms ps

   ```

2. Verify the tray process is active:

   ```bash
   pgrep -f lmstudio_tray.py

   ```

3. Check logs for errors:

   ```bash
   cat .logs/lmstudio_tray.log

   ```

4. Manually test GTK3:

   ```bash
   ./venv/bin/python3 -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk; print('GTK3 OK')"

   ```

## Why Python 3.10?

PyGObject (Python GTK3 bindings) has a complex setup:

- **PyGObject binaries** (`.so` files) are pre-compiled for Python 3.10 in Debian/Ubuntu
- System Python 3.12 doesn't have pre-compiled PyGObject binaries
- Recompiling from source requires C compiler, GObject headers, and pkg-config
- Python 3.10 is still actively maintained (until Oct 2026) and secure
- venv with `--system-site-packages` gives us the best of both worlds:
  - Isolated Python environment
  - Access to pre-compiled system PyGObject + GTK3
  - No compilation needed, fast setup

## Python 3.12+ Support

To support Python 3.12 natively would require one of these approaches:

### Option 1: Install Build Tools (not recommended)

```bash
sudo apt install libgirepository-1.0-dev pkg-config build-essential
pip install PyGObject  # This would compile from source

```

- ❌ Slow (compilation takes 2-5 minutes)
- ❌ More dependencies (compiler, headers)
- ❌ Harder to maintain

### Option 2: Wait for Debian/Ubuntu Packages

```bash
# Would work when these are available (Python 3.12 LTS support)
sudo apt install python3.12-gi gir1.2-gtk-3.0

```

- ❌ Not yet available in most distributions
- ⏳ Will take time for distribution support

### Option 3: Use Docker (alternative)

```dockerfile
FROM python:3.12
RUN apt install -y libgirepository-1.0-dev python3-gi

```

- ❌ Adds container complexity
- ⏳ More setup overhead

### Our Solution: Python 3.10 venv

```bash
./setup.sh  # 5 seconds, uses pre-compiled binaries

```

- ✅ Pre-compiled binaries
- ✅ Instant setup
- ✅ No extra dependencies
- ✅ Clean isolation

We recommend staying with **Python 3.10** for the foreseeable future.
