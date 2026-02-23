# Setup Guide

The `setup.sh` script automates the complete setup process for LM Studio Tray Manager.

## Table of Contents

- [What setup.sh Does](#what-setupsh-does)
- [Installation Types](#installation-types)
  - [Binary Release (Recommended)](#binary-release-recommended)
  - [Python Package Release](#python-package-release)
- [Quick Start](#quick-start)
- [Dry-run Mode](#dry-run-mode)
- [Setup Script Outputs](#setup-script-outputs)
  - [If LM Studio Daemon is Missing](#if-lm-studio-daemon-is-missing)
  - [If LM Studio Desktop App is Missing](#if-lm-studio-desktop-app-is-missing)
  - [If Python 3.10 is Missing](#if-python-310-is-missing)
- [What's Inside the venv?](#whats-inside-the-venv)
- [File Structure After Setup](#file-structure-after-setup)
  - [For Binary Release](#for-binary-release)
  - [For Python Package](#for-python-package)
- [Environment Variables](#environment-variables)
- [Log File Format](#log-file-format)
  - [setup.log](#setuplog)
  - [lmstudio_autostart.log](#lmstudio_autostartlog)
  - [lmstudio_tray.log](#lmstudio_traylog)
- [Troubleshooting](#troubleshooting)
  - [venv not found](#venv-not-found)
  - [Checking Logs](#checking-logs)
  - [Network Prerequisites for Updates](#network-prerequisites-for-updates)
  - [PyGObject Import Errors](#pygobject-import-errors)
  - [System Tray Icon Not Appearing](#system-tray-icon-not-appearing)
- [Why Python 3.10?](#why-python-310)
- [Python 3.12+ Support](#python-312-support)
  - [Option 1: Install Build Tools (not recommended)](#option-1-install-build-tools-not-recommended)
  - [Option 2: Wait for Debian/Ubuntu Packages](#option-2-wait-for-debianubuntu-packages)
  - [Option 3: Use Docker (alternative)](#option-3-use-docker-alternative)
  - [Our Solution: Python 3.10 venv](#our-solution-python-310-venv)
- [Next Steps](#next-steps)

## What setup.sh Does

The setup script automatically detects your installation type and configures accordingly. It checks for and optionally installs:

1. **LM Studio Daemon (llmster)** - Headless backend for model inference
   - Checks if `lms` CLI is available
   - If not found: Opens download page and asks to install

2. **LM Studio Desktop App** - GUI for model management
   - Intelligently detects .deb package installation
   - Searches for AppImage in: script directory, $HOME/Apps, $HOME/LM_Studio, $HOME/Applications, $HOME/.local/bin, /opt/lm-studio
   - Auto-detects both standard and versioned AppImage formats (e.g., LM-Studio-0.4.3-*.AppImage)
   - Allows manual AppImage path input
   - Optional (only needed for `--gui` option)

3. **Installation Type Detection** - Automatically determines setup path
   - **Binary Release:** Detects `lmstudio-tray-manager` binary in script directory
   - **Python Package:** No binary found - proceeds with Python setup
   - This detection is **non-intrusive**: just a file existence check

4. **Python 3.10** - Required for PyGObject/GTK3 compatibility
   - **Only checked for Python package releases** (step 3 must detect no binary)
   - Installs automatically if missing (via `apt`)
   - Binary releases skip this step entirely

5. **Python Virtual Environment** - Isolated Python environment (Python releases only)
   - Creates venv with system site-packages
   - Enables GTK3 introspection and PyGObject
   - **Skipped entirely for binary releases** (all dependencies already bundled)

## Installation Types

The setup script automatically detects your installation type:

### Binary Release (Recommended)

**Detection:** Script finds `lmstudio-tray-manager` binary in the script directory

**What happens:**

- ✓ No Python venv needed (dependencies bundled in binary)
- ✓ Fast setup (only checks dependencies)
- ✓ Checks for LM Studio daemon
- ✓ Checks for LM Studio desktop app
- ✓ Minimal dependencies (no Python installation required)

**Next steps:**

```bash
./lmstudio-tray-manager --auto-start-daemon
```

### Python Package Release

**Detection:** No `lmstudio-tray-manager` binary found

**What happens:**

- ✓ Creates Python virtual environment (./venv)
- ✓ Checks for LM Studio daemon
- ✓ Checks for LM Studio desktop app
- ✓ Checks for Python 3.10 (installs if missing)
- ✓ Sets up GTK3 and PyGObject support

**Next steps:**

```bash
./lmstudio_autostart.sh
```

## Quick Start

```bash
# Run the setup script (auto-detects installation type)
./setup.sh

# Preview setup actions without changing your system
./setup.sh --dry-run

# Show available setup options
./setup.sh --help
```

The setup will:

- ✓ Check for LM Studio daemon
- ✓ Check for LM Studio desktop app
- ✓ Detect if binary or Python package
- ✓ Create venv (Python packages only)
- ✓ Install Python 3.10 if needed (Python packages only)

## Dry-run Mode

Run `./setup.sh --dry-run` to validate the system and preview setup actions without making changes.

In normal mode (`./setup.sh`), the script can install missing prerequisites and create the virtual environment.

Dry-run mode:

- Performs all detection and prerequisite checks
- Prints commands it would execute for install/setup steps
- Does **not** install packages, remove folders, create venvs, or modify files
- Writes a dry-run summary to `.logs/setup.log`

Example output for Python package releases (Steps 4 and 5 are skipped for binary releases):

```text
[INFO] Running setup in dry-run mode (no changes will be applied)
[CHECK] LM Studio daemon (lms): found
[CHECK] LM Studio desktop app: not found
[DRY-RUN] Would open LM Studio download page for desktop app guidance
[CHECK] Python 3.10: found
[DRY-RUN] Would recreate virtual environment in: ./venv
[DRY-RUN] Would run: python3.10 -m pip install --upgrade pip
[DONE] Dry-run completed successfully (0 changes applied)
```

**Note:** For binary releases, the Python environment steps (Steps 4 and 5) are automatically skipped by the gating logic in `setup.sh`, so you will not see the virtualenv or pip installation lines in the dry-run output.

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

### For Binary Release

After running `./setup.sh`:

```files
.
├── lmstudio-tray-manager       # Pre-built binary
├── .logs/                      # 📝 Log files directory
│   └── setup.log               # Setup script log (created during setup)
```

**Note:** No venv created; binary is self-contained.

### For Python Package

After running `./setup.sh`:

```files
.
├── venv/                       # 🆕 Python virtual environment
├── lmstudio_autostart.sh       # Automation script
├── lmstudio_tray.py            # Tray monitor script
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
./lmstudio_autostart.sh -L  # Interactive model selection + loads selected model in daemon mode

```

## Log File Format

All log files include a standardized header at the start that shows when the script was run:

### setup.log

```text
================================================================================
LM Studio Setup Log
Started: 2026-02-20 21:54:38
================================================================================
[2026-02-20 21:54:38] [INFO] --- LM-Studio-Tray-Manager Setup ---
[2026-02-20 21:54:38] [OK] LM Studio daemon found
...
```

### lmstudio_autostart.log

```text
================================================================================
LM Studio Autostart Log
Started: 2026-02-20 21:55:18
================================================================================
2026-02-20 21:55:18 🚀 Starting llmster headless daemon...
2026-02-20 21:55:18 ✅ llmster started.
...
```

### lmstudio_tray.log

```text
================================================================================
LM Studio Tray Monitor Log
Started: 2026-02-20 21:55:18
================================================================================
2026-02-20 21:55:18,988 - INFO - Tray script started
2026-02-20 21:55:19,123 - INFO - Status change: WARN -> INFO
...
```

All output is logged to the `.logs/` directory (view logs in [USE.md](USE.md)).

## Troubleshooting

### venv not found

If the autostart script doesn't find your venv:

```bash
# Set VENV_DIR explicitly (or add to .bashrc/.zshrc)
export VENV_DIR=$(pwd)/venv
./lmstudio_autostart.sh
```

Or activate and use directly:

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

### Network Prerequisites for Updates

The tray monitor requires outbound HTTPS access to GitHub for update checks. If you see "Unable to check for updates.", verify network connectivity and check logs. See [USE.md](USE.md) for detailed troubleshooting steps.

### PyGObject Import Errors

If you see `ImportError: cannot import name '_gi'`:

1. Verify Python 3.10 is being used:

   ```bash
   ./venv/bin/python3 --version
   ```

2. See [USE.md](USE.md) for log viewing instructions.

### System Tray Icon Not Appearing

If you encounter network issues, verify connectivity and check logs.

1. See [USE.md](USE.md) for detailed troubleshooting steps.

If you see `ImportError: cannot import name '_gi'`:

1. Verify Python 3.10 is being used:

   ```bash
      ./venv/bin/python3 --version
      ```

2. See [USE.md](USE.md) for log viewing instructions.

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

## Next Steps

After setup is complete, proceed to [USE.md](USE.md) to learn how to run and use the application.
