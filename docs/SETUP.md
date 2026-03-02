# Setup Guide

> ⚠️ **Linux‑only application.** The tray manager relies on GTK3; Windows
> and macOS are not supported yet. AppImage support is universal across Linux
> distributions. Package‑manager automation is available for **apt, dnf,
> pacman, zypper, and apk**; other distros receive manual‑install guidance.

The `setup.sh` script automates the complete setup process for LM Studio Tray Manager.

## Table of Contents

- [Setup Guide](#setup-guide)
  - [Table of Contents](#table-of-contents)
  - [What setup.sh Does](#what-setupsh-does)
  - [Installation Types](#installation-types)
    - [Binary Release (Recommended)](#binary-release-recommended)
    - [Python Package Release](#python-package-release)
  - [Quick Start](#quick-start)
  - [Dry-run Mode](#dry-run-mode)
  - [Setup Script Outputs](#setup-script-outputs)
    - [If LM Studio Daemon is Missing](#if-lm-studio-daemon-is-missing)
    - [If LM Studio Desktop App is Missing](#if-lm-studio-desktop-app-is-missing)
    - [If Python 3 is Missing](#if-python-3-is-missing)
  - [What's Inside the venv?](#whats-inside-the-venv)
  - [File Structure After Setup](#file-structure-after-setup)
    - [For Binary Release](#for-binary-release)
    - [For Python Package](#for-python-package)
  - [Environment Variables](#environment-variables)
  - [Log File Format](#log-file-format)
    - [setup.log](#setuplog)
    - [lmstudio\_autostart.log](#lmstudio_autostartlog)
    - [lmstudio\_tray.log](#lmstudio_traylog)
  - [Troubleshooting](#troubleshooting)
    - [venv not found](#venv-not-found)
    - [Checking Logs](#checking-logs)
    - [Network Prerequisites for Updates](#network-prerequisites-for-updates)
    - [PyGObject Import Errors](#pygobject-import-errors)
    - [System Tray Icon Not Appearing](#system-tray-icon-not-appearing)
  - [Python Version Notes](#python-version-notes)
  - [Next Steps](#next-steps)

## What setup.sh Does

The setup script automatically detects your installation type and configures accordingly. It checks for and optionally installs:

1. **LM Studio Daemon (llmster)** - Headless backend for model inference
   - Checks if `lms` CLI is available
   - If not found: Opens download page and asks to install

2. **LM Studio Desktop App** - GUI for model management
   - Detects natively-installed packages (deb/rpm/pacman)
   - Searches for AppImage in: script directory, $HOME/Apps, $HOME/LM_Studio, $HOME/Applications, $HOME/.local/bin, /opt/lm-studio
   - Auto-detects both standard and versioned AppImage formats (e.g., LM-Studio-0.4.3-*.AppImage)
   - Allows manual AppImage path input
   - Optional (only needed for `--gui` option)

3. **Installation Type Detection** - Automatically determines setup path
   - **Binary Release:** Detects `lmstudio-tray-manager` binary in script directory
   - **Python Package:** No binary found - proceeds with Python setup
   - This detection is **non-intrusive**: just a file existence check

4. **GTK3/GObject typelibs** - Needed by both binary and Python package releases
   - Checked on every run, regardless of installation type
   - Uses a simple Python import test or file lookup
   - If missing, prompts to install via the detected package manager
     (apt, dnf, pacman, zypper, or apk). When no manager is found,
     manual instructions are printed for all supported distros.
   - If the user declines, setup aborts with an explanatory error

5. **Python 3** - Required for PyGObject/GTK3 compatibility (packages only)
   - **Only checked for Python package releases** (step 3 must detect no binary)
   - Uses the system `python3` interpreter (or `python3.10` if that is what
     the system provides)
   - Installs automatically if missing via the detected package manager
   - When no supported manager is found, manual instructions are shown
   - Binary releases skip this step entirely

6. **Python Virtual Environment** - Isolated Python environment (Python releases only)
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
- ✓ Checks for GTK3/GObject typelibs (installs if missing)
- ✓ Checks for Python 3 (installs if missing)
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
- ✓ Install Python 3 if needed (Python packages only)
- ✓ Check for GTK3/GObject typelibs (installs if missing)

## Dry-run Mode

Run `./setup.sh --dry-run` to validate the system and preview setup actions without making changes.

In normal mode (`./setup.sh`), the script can install missing prerequisites and create the virtual environment.

Dry-run mode:

- Performs all detection and prerequisite checks
- Prints commands it would execute for install/setup steps
- Does **not** install packages, remove folders, create venvs, or modify files
- Writes a dry-run summary to `.logs/setup.log`

Example output for Python package releases (Steps 4 and 5 are skipped for binary releases):

```bash
[INFO] Running setup in dry-run mode (no changes will be applied)
[CHECK] LM Studio daemon (lms): found
[CHECK] LM Studio desktop app: not found
[DRY-RUN] Would open LM Studio download page for desktop app guidance
[CHECK] GTK3/GObject typelibs: missing (would install gir1.2-gtk-3.0)
[CHECK] Python 3: found (python3.10)
[DRY-RUN] Would recreate virtual environment in: ./venv
[DRY-RUN] Would run: python3.10 -m pip install --upgrade pip
[DONE] Dry-run completed successfully (0 changes applied)
```

**Note:** For binary releases, the Python environment steps (Steps 4 and 5) are automatically skipped by the gating logic in `setup.sh`, so you will not see the virtualenv or pip installation lines in the dry-run output.

## Setup Script Outputs

### If LM Studio Daemon is Missing

```bash
⚠ LM Studio daemon not found
  The daemon (llmster) is required for the automation scripts.
  
  Would you like to download LM Studio daemon? [y/n]:

```

Selecting `y` opens the download page. You'll need to install it manually from <https://lmstudio.ai/>

### If LM Studio Desktop App is Missing

```bash
⚠ LM Studio desktop app not found
  The desktop app is required for the --gui option.

  Choose installation method:
    1) Download installer/package from lmstudio.ai
    2) Use AppImage (manual download)
    3) Skip (can be installed later)

```

**Option 1**: Download from <https://lmstudio.ai/download> and install using
your distro's package manager, for example:

```bash
# Debian/Ubuntu
sudo apt install ./LM-Studio-0.4.4-1-x64.deb
# Fedora/RHEL
sudo dnf install ./LM-Studio-0.4.4-1-x64.rpm
# Arch – use the AppImage or an AUR helper
# All distros – AppImage (no install required)
chmod +x LM-Studio-0.4.4-1-x64.AppImage && ./LM-Studio-0.4.4-1-x64.AppImage

```

**Option 2**: Provide path to AppImage file:

```bash
# example (replace with actual path and file name)
Enter path to AppImage file (or directory containing it): /home/user/Downloads/LM-Studio-0.4.4-1-x64.AppImage

```

### If Python 3 is Missing

```bash
⚠ Python 3 not found
  Python 3 is required.

  Would you like to install Python 3? [y/n]:

```

Selecting `y` installs Python 3 via the detected package manager
(requires sudo password). If no supported manager is found, manual
installation instructions are displayed.

## What's Inside the venv?

- **Python 3** (any version available on the system)
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

```bash
================================================================================
LM Studio Setup Log
Started: 2026-02-20 21:54:38
================================================================================
[2026-02-20 21:54:38] [INFO] --- LM-Studio-Tray-Manager Setup ---
[2026-02-20 21:54:38] [OK] LM Studio daemon found
...
```

### lmstudio_autostart.log

```bash
================================================================================
LM Studio Autostart Log
Started: 2026-02-20 21:55:18
================================================================================
2026-02-20 21:55:18 🚀 Starting llmster headless daemon...
2026-02-20 21:55:18 ✅ llmster started.
...
```

### lmstudio_tray.log

```bash
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
# Linux example
source ./venv/bin/activate
python3 ./lmstudio_tray.py
```

```bash
# Windows example (if using WSL or similar)
source ./venv/Scripts/activate.ps1
python ./lmstudio_tray.py
```

```bash
# macOS example (if using pyenv or similar)
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

The tray monitor requires outbound HTTPS access to GitHub for update checks. If you see "Unable to check for updates." or encounter network issues, verify network connectivity and check logs. See [USE.md](USE.md) for detailed troubleshooting steps.

### PyGObject Import Errors

If you see `ImportError: cannot import name '_gi'`:

1. Verify which Python is being used:

   ```bash
   ./venv/bin/python3 --version
   ```

2. See [USE.md](USE.md) for log viewing instructions.

### System Tray Icon Not Appearing

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

## Python Version Notes

The setup script uses `python3.10` when it is available (mirroring `build.sh`),
otherwise it falls back to any `python3` found in `PATH`. All Python 3 versions
have good PyGObject compatibility; the venv is created with
`--system-site-packages` so GTK3 introspection data installed at the system
level is always accessible regardless of the Python version used.

## Next Steps

After setup is complete, proceed to [USE.md](USE.md) to learn how to run and use the application.
