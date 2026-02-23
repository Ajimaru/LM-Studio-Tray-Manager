# Using LM Studio Tray Manager

This guide covers how to use the LM Studio Tray Manager application after setup.

## Table of Contents

- [Using LM Studio Tray Manager](#using-lm-studio-tray-manager)
  - [Table of Contents](#table-of-contents)
  - [Quick Start](#quick-start)
    - [Binary Release](#binary-release)
    - [Python Package Release](#python-package-release)
  - [Running the Application](#running-the-application)
    - [Binary Release (Running)](#binary-release-running)
    - [Python Package Release (Running)](#python-package-release-running)
    - [Autostart on Login](#autostart-on-login)
  - [Command-Line Options](#command-line-options)
    - [Available Flags](#available-flags)
    - [Example Usage](#example-usage)
  - [System Tray Interface](#system-tray-interface)
    - [Status Indicators](#status-indicators)
    - [Right-Click Menu](#right-click-menu)
    - [Menu Options](#menu-options)
  - [Desktop App Launch](#desktop-app-launch)
    - [How "Start Desktop App" Works](#how-start-desktop-app-works)
    - [How "Start LM Studio Daemon" Works](#how-start-lm-studio-daemon-works)
    - [Conflict Handling](#conflict-handling)
  - [Model Management](#model-management)
    - [Interactive Model Selection](#interactive-model-selection)
    - [Autoload Models](#autoload-models)
  - [Monitoring and Logs](#monitoring-and-logs)
    - [View Logs in Real-Time](#view-logs-in-real-time)
    - [Understanding Log Files](#understanding-log-files)
    - [Debug Mode](#debug-mode)
  - [Troubleshooting](#troubleshooting)
    - [Daemon Not Starting](#daemon-not-starting)
    - [Desktop App Won't Launch](#desktop-app-wont-launch)
    - [Tray Icon Issues](#tray-icon-issues)
    - [High CPU Usage](#high-cpu-usage)

## Quick Start

### Binary Release

```bash
# Make executable (if needed)
chmod +x ./lmstudio-tray-manager

# Run with daemon autostart
./lmstudio-tray-manager --auto-start-daemon

# Monitor logs (in another terminal)
tail -f .logs/lmstudio_tray.log
```

### Python Package Release

```bash
# Run the autostart script
./lmstudio_autostart.sh

# Or manually in the foreground
source ./venv/bin/activate
python3 ./lmstudio_tray.py

# Monitor logs (in another terminal)
tail -f .logs/lmstudio_tray.log
```

## Running the Application

### Binary Release (Running)

The binary is self-contained and includes all dependencies:

```bash
# Basic run (no autostart)
./lmstudio-tray-manager

# With daemon autostart
./lmstudio-tray-manager --auto-start-daemon

# With GUI mode
./lmstudio-tray-manager --gui
```

### Python Package Release (Running)

Run via the convenience script:

```bash
# Starts daemon with tray monitor
./lmstudio_autostart.sh

# With interactive model selection
./lmstudio_autostart.sh -L

# With debug output
export LM_AUTOSTART_DEBUG=1
./lmstudio_autostart.sh
```

Or run directly:

```bash
source ./venv/bin/activate
python3 ./lmstudio_tray.py [OPTIONS]
```

### Autostart on Login

For automatic startup on login, create a desktop entry:

```bash
mkdir -p ~/.config/autostart/
cat > ~/.config/autostart/lmstudio-daemon.desktop << 'EOF'
[Desktop Entry]
Type=Application
Name=LM Studio Daemon
Exec=/path/to/LM-Studio/lmstudio_autostart.sh
X-GNOME-Autostart-enabled=true
Hidden=false
EOF
```

Then enable autostart in your desktop environment settings.

## Command-Line Options

### Available Flags

```bash
--help              Show help message
--version           Show version and exit
--debug             Run in debug mode with verbose output
--gui               Start with desktop GUI mode (stops daemon first)
--auto-start-daemon Start daemon automatically on launch
```

### Example Usage

```bash
# Show version
./lmstudio-tray-manager --version

# Run with debug output
./lmstudio-tray-manager --debug

# Launch GUI mode (if desktop app installed)
./lmstudio-tray-manager --gui

# Start daemon and monitor in tray
./lmstudio-tray-manager --auto-start-daemon
```

## System Tray Interface

The application displays a system tray icon with status indicators and a context menu.

### Status Indicators

The tray icon changes based on application status:

| Icon | Meaning | Status |
| ---- | ------- | ------ |
| ❌ | Fail | Daemon and desktop app both not installed |
| ⚠️ | Warn | Neither daemon nor desktop app is running |
| ℹ️ | Info | Daemon or desktop app running, but no model loaded |
| ✅ | OK | A model is loaded and ready |

### Right-Click Menu

Right-click on the tray icon to open the context menu with available options.

### Menu Options

The menu shows the following options (availability depends on current state):

- **Start LM Studio Daemon** - Starts the headless daemon
- **Stop LM Studio Daemon** - Stops the running daemon
- **Start LM Studio Desktop App** - Launches the GUI (stops daemon first)
- **Stop LM Studio Desktop App** - Closes the desktop app
- **Reload Status** - Manually refresh the tray status
- **Check for Updates** - Check GitHub for new releases
- **Open Settings** - (if implemented) Access application settings
- **Quit** - Exit the tray manager

Each option is **context-aware**: unavailable actions are grayed out.

## Desktop App Launch

### How "Start Desktop App" Works

When you click "Start Desktop App":

1. **Priority 1**: Looks for installed `.deb` package

   ```bash
   which lm-studio  # or dpkg -l | grep lm-studio
   ```

2. **Priority 2**: Searches for AppImage in common locations:
   - Script directory (`.`)
   - `~/Apps`
   - `~/LM_Studio`
   - `$SCRIPT_DIR`
   - `~/.local/bin`
   - `/opt/lm-studio`

3. **Auto-detection**: Recognizes both standard and versioned formats:

   ```text
   LM-Studio.AppImage
   LM-Studio-0.4.3-*.AppImage
   ```

4. **On Launch**:
   - Stops daemon first (if running)
   - Launches GUI application
   - Shows desktop notification on success or error
   - Logs all actions to `.logs/lmstudio_tray.log`

### How "Start LM Studio Daemon" Works

When you click "Start LM Studio Daemon":

1. **Tries CLI commands** in order:
   - `lms`
   - `llmster`
   - Other daemon variants with fallback logic

2. **Conflict handling**:
   - Stops desktop app first (if running)
   - Then starts the daemon

3. **Verification**:
   - Confirms daemon started successfully
   - Monitors daemon process

### Conflict Handling

The tray manager prevents conflicts between daemon and desktop app:

- **Starting daemon**: Automatically stops desktop app first
- **Starting desktop app**: Automatically stops daemon first
- **Status updates**: Reflects current state of both processes
- **Notifications**: Informs user of any state changes

## Model Management

### Interactive Model Selection

If you have multiple models, you can select which one to load:

```bash
# Interactive selection + daemon autostart
./lmstudio_autostart.sh -L

# Set selection timeout (default 30 seconds)
export LM_AUTOSTART_SELECT_TIMEOUT=60
./lmstudio_autostart.sh -L
```

The script will:

1. List available models
2. Prompt you to select one
3. Load the selected model in daemon mode
4. Start the system tray monitor

### Autoload Models

To automatically load a specific model on startup, set the model in LM Studio daemon settings:

```bash
lms ls  # List available models
```

Then configure your default model in the daemon settings.

## Monitoring and Logs

### View Logs in Real-Time

```bash
# Watch tray monitor logs
tail -f .logs/lmstudio_tray.log

# Watch daemon startup logs
tail -f .logs/lmstudio_autostart.log

# Watch all logs simultaneously
tail -f .logs/*.log

# In separate terminals for combined view
# Terminal 1:
tail -f .logs/lmstudio_autostart.log

# Terminal 2:
tail -f .logs/lmstudio_tray.log
```

### Understanding Log Files

The tray manager creates three log files:

| Log File | Purpose | Created By |
| -------- | ------- | ---------- |
| `.logs/setup.log` | Installation history | `setup.sh` |
| `.logs/lmstudio_autostart.log` | Daemon startup events | `lmstudio_autostart.sh` |
| `.logs/lmstudio_tray.log` | Tray monitor activity | `lmstudio_tray.py` |

**Log Format Examples:**

Setup log:

```text
[2026-02-20 21:54:38] [INFO] --- LM-Studio-Tray-Manager Setup ---
[2026-02-20 21:54:38] [OK] LM Studio daemon found
```

Autostart log:

```text
2026-02-20 21:55:18 🚀 Starting llmster headless daemon...
2026-02-20 21:55:18 ✅ llmster started.
```

Tray log:

```text
2026-02-20 21:55:18,988 - INFO - Tray script started
2026-02-20 21:55:19,123 - INFO - Status change: WARN -> INFO
```

Each log file is **recreated** when the script starts, ensuring fresh logs for each run.

### Debug Mode

Enable debug mode for verbose output:

```bash
# Via command line
./lmstudio-tray-manager --debug

# Via environment variable
export LM_AUTOSTART_DEBUG=1
./lmstudio_autostart.sh

# View debug output
tail -f .logs/lmstudio_tray.log
```

Debug mode shows:

- Detailed process state changes
- API communication logs
- Model loading information
- SystemTray icon changes
- Error stack traces

## Troubleshooting

### Daemon Not Starting

**Problem**: Daemon fails to start or exits immediately

**Solutions**:

1. Check if LM Studio daemon is installed:

   ```bash
   lms --version
   llmster --version
   ```

2. Check logs for errors:

   ```bash
   tail -f .logs/lmstudio_autostart.log
   tail -f .logs/lmstudio_tray.log
   ```

3. Try starting daemon manually:

   ```bash
   lms start
   lms ps  # Check if running
   ```

4. Enable debug mode:

   ```bash
   ./lmstudio-tray-manager --debug
   ```

### Desktop App Won't Launch

**Problem**: "Start Desktop App" button doesn't work

**Solutions**:

1. Verify desktop app is installed:

   ```bash
   # Check for .deb installation
   which lm-studio
   dpkg -l | grep lm-studio

   # Check for AppImage
   find ~ -name "LM-Studio*.AppImage" 2>/dev/null
   ```

2. Check tray logs:

   ```bash
   grep -i "desktop" .logs/lmstudio_tray.log
   ```

3. Disable daemon first (they conflict):

   ```bash
   lms stop
   # Then try starting desktop app via tray menu
   ```

4. Manually launch:

   ```bash
   # If AppImage
   ~/LM_Studio/LM-Studio.AppImage

   # If .deb installed
   lm-studio
   ```

### Tray Icon Issues

**Problem**: Tray icon doesn't appear despite app running

**Solutions**:

1. Verify app is running:

   ```bash
   pgrep -f lmstudio_tray.py
   ps aux | grep lmstudio
   ```

2. Check for GTK3 issues:

   ```bash
   ./venv/bin/python3 -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk; print('GTK3 OK')"
   ```

3. Install missing GTK packages:

   ```bash
   sudo apt install gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
   ```

4. Check logs:

   ```bash
   cat .logs/lmstudio_tray.log | grep -i "error\|icon\|tray"
   ```

5. Try debug mode:

   ```bash
   ./lmstudio-tray-manager --debug 2>&1 | tee debug.log
   ```

### High CPU Usage

**Problem**: Application consuming excessive CPU

**Solutions**:

1. Check what's running:

   ```bash
   top -p $(pgrep -f lmstudio_tray.py)
   ```

2. Check for stuck processes:

   ```bash
   ps aux | grep lmstudio
   lms ps
   ```

3. Stop and restart:

   ```bash
   pkill -f lmstudio_tray.py
   sleep 2
   ./lmstudio_autostart.sh
   ```

4. Check logs for errors:

   ```bash
   tail -100 .logs/lmstudio_tray.log | grep -i "error"
   ```

5. Monitor in real-time:

   ```bash
   watch -n 1 'ps aux | grep lmstudio'
   ```
