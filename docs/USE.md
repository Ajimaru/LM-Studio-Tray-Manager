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
    - [Left-Click Menu](#left-click-menu)
    - [Menu Options](#menu-options)
  - [Desktop App Launch](#desktop-app-launch)
    - [How "Start Desktop App" Works](#how-start-desktop-app-works)
    - [How "Start LM Studio Daemon" Works](#how-start-lm-studio-daemon-works)
    - [Conflict Handling](#conflict-handling)
  - [Model Management](#model-management)
    - [Interactive Model Selection](#interactive-model-selection)
    - [Autoload Models](#autoload-models)
      - [Option 1: Via LM Studio CLI (Quick)](#option-1-via-lm-studio-cli-quick)
      - [Option 2: Via LM Studio GUI](#option-2-via-lm-studio-gui)
      - [Option 3: Via Daemon Configuration File](#option-3-via-daemon-configuration-file)
  - [Monitoring and Logs](#monitoring-and-logs)
    - [Common Errors \& Troubleshooting](#common-errors--troubleshooting)
      - [GSettings Schema Crash](#gsettings-schema-crash)
    - [View Logs in Real-Time](#view-logs-in-real-time)
    - [Understanding Log Files](#understanding-log-files)
    - [Debug Mode](#debug-mode)
  - [Troubleshooting](#troubleshooting)
    - [Daemon Not Starting](#daemon-not-starting)
    - [WebSocket Authentication Error](#websocket-authentication-error)
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
# Make autostart script executable (if needed)
chmod +x ./lmstudio_autostart.sh

# Run the autostart script
./lmstudio_autostart.sh

# Or manually in the foreground
source ./venv/bin/activate
python3 ./lmstudio_tray.py

# Monitor logs (in another terminal)
tail -f ./logs/lmstudio_autostart.log
tail -f ./logs/lmstudio_tray.log
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
./lmstudio_autostart.sh --debug
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
Exec=/full/path/to/your/lmstudio_autostart.sh
X-GNOME-Autostart-enabled=true
Hidden=false
EOF
```

**Important:** Replace `/full/path/to/your/lmstudio_autostart.sh` with the absolute path to your installed script:

- If you installed to your home directory: run `pwd` in your LM-Studio-Tray-Manager directory to get the full path, then append `/lmstudio_autostart.sh`
- To find the script location quickly: `which lmstudio_autostart.sh` or check your [SETUP.md](SETUP.md) installation section for default locations

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

### Left-Click Menu

Left-click on the tray icon to open the context menu with available options.

### Menu Options

The menu shows the following options (availability depends on current state):

- **Start Daemon (Headless)** - Starts the headless daemon (stops desktop app first if running)
- **Stop Daemon** - Stops the running daemon
- **Start Desktop App** - Launches the GUI (stops daemon first)
- **Stop Desktop App** - Closes the desktop app
- **Show Status** - Manually refresh and display the tray status
- **Options** - Submenu containing:
  - **Configuration** - Access application settings
  - **Check for updates** - Check GitHub for new releases
- **About** - Display application information
- **Quit Tray** - Exit the tray manager

Each option is **context-aware**: unavailable actions are grayed out.

## Desktop App Launch

### How "Start Desktop App" Works

When you click "Start Desktop App":

1. **Priority 1**: Looks for installed `.deb` package

   ```bash
   # Quick check: Look for executable in PATH
   which lm-studio

   # Alternative: Check installed Debian packages (if which returns nothing)
   dpkg -l | grep lm-studio
   ```

2. **Priority 2**: Searches for AppImage in common locations:
   - Script directory (`.`)
   - `~/Apps`
   - `~/LM_Studio`
   - `$SCRIPT_DIR`
   - `~/.local/bin`
   - `/opt/lm-studio`

3. **Auto-detection**: Recognizes both standard and versioned formats:

   ```bash
   LM-Studio.AppImage
   LM-Studio-0.4.3-*.AppImage
   ```

4. **On Launch**:
   - Stops daemon first (if running)
   - Launches GUI application
   - Automatically appends `--no-sandbox` when an AppImage is detected; this
     avoids the common SUID sandbox error for Chromium-based AppImages
     (see issue #62).
   - Recognises AppImage processes so the tray icon updates from red after
     the GUI starts
   - Shows desktop notification on success or error
   - Logs all actions to `.logs/lmstudio_tray.log`
   - All of the above logic is executed in a background thread; the tray
     menu remains responsive and clicks are not blocked while the desktop
     app is launching.

### How "Start LM Studio Daemon" Works

When you click "Start LM Studio Daemon":

1. **Tries CLI commands** in order:
   - `lms daemon up` (preferred LM Studio CLI wrapper)
   - `llmster daemon start` (direct daemon command)

   If the primary commands fail, also tries: `lms up`, `lms start`, `llmster up`, `llmster start`

2. **Conflict handling**:
   - Stops desktop app first (if running)
   - Then starts the daemon   - The daemon start sequence runs in a background thread so the
     tray menu remains usable while the service spins up.

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

To automatically load a specific model on startup, configure a default model using one of these methods:

#### Option 1: Via LM Studio CLI (Quick)

```bash
# List available models to find the exact name/ID
lms ls

# Load a specific model into the daemon
lms load <model-name-or-id>

# Verify it's set
lms ps
```

Example:

```bash
lms load "meta-llama/llama-2-7b-hf"
```

#### Option 2: Via LM Studio GUI

1. Start the desktop app: `./lmstudio_autostart.sh --gui`
2. Select your desired model in the GUI
3. The model will persist as default

#### Option 3: Via Daemon Configuration File

The LM Studio daemon stores its configuration in `~/.lmstudio/config.json`. You can manually edit this file and set the default model key to `"default_model": "<model-id>"`.

Example configuration snippet (add the `"default_model"` key to your existing config file, don't replace the entire file):

```json
{
  "default_model": "meta-llama/llama-2-7b-hf"
}
```

**Note**: After setting a default model with any method, the next time the daemon starts (via `lmstudio_autostart.sh` or `lms daemon up`), it will automatically load your configured model.

## Monitoring and Logs

### Common Errors & Troubleshooting

#### GSettings Schema Crash

If you run the binary and immediately see a GLib-GIO-ERROR about a missing
`antialiasing` key, the underlying GTK library failed to locate the
GSettings schemas.  The tray manager attempts to set
`GSETTINGS_SCHEMA_DIR` automatically, but in some minimal chroot or
AppImage environments that directory may not be mounted.  The quick fixes
are:

```bash
sudo apt install gsettings-desktop-schemas
GSETTINGS_SCHEMA_DIR=/usr/share/glib-2.0/schemas ./lmstudio-tray-manager
```

This error is only relevant for the standalone binary; the Python package
version inherits whatever environment your shell already provides.

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

The tray manager creates four log files:

| Log File | Purpose | Created By |
| -------- | ------- | ---------- |
| `.logs/setup.log` | Installation history | `setup.sh` |
| `.logs/lmstudio_autostart.log` | Daemon startup events | `lmstudio_autostart.sh` |
| `.logs/lmstudio_tray.log` | Tray monitor activity | `lmstudio_tray.py` |
| `.logs/build.log` | Build process details | `build.sh` or `build_binary.py` |

**Log Format Examples:**

Setup log:

```bash
[2026-02-20 21:54:38] [INFO] --- LM-Studio-Tray-Manager Setup ---
[2026-02-20 21:54:38] [OK] LM Studio daemon found
```

Autostart log:

```bash
2026-02-20 21:55:18 🚀 Starting llmster headless daemon...
2026-02-20 21:55:18 ✅ llmster started.
```

Tray log:

```bash
2026-02-20 21:55:18,988 - INFO - Tray script started
2026-02-20 21:55:19,123 - INFO - Status change: WARN -> INFO
```

Build log:

```bash
[2026-02-20 22:00:00] [INFO] Starting build process...
[2026-02-20 22:01:30] [OK] Build completed successfully.
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
- System tray icon changes
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

### WebSocket Authentication Error

**Problem**: Error message `Invalid passkey for lms CLI client` appears

**Cause**: Stale daemon processes with outdated authentication tokens

**Automatic Handling**: The script automatically:

- Cleans up old daemon processes on startup
- Clears stale authentication tokens
- Restarts the daemon fresh

**Manual Solutions** (if automatic cleanup fails):

1. Kill all LM Studio daemon processes:

   ```bash
   pkill -f "lms"
   pkill -f "llmster"
   ```

2. Clear authentication tokens:

   ```bash
   # Remove token files (location may vary by LM Studio version)
   rm -f ~/.lmstudio/auth_token
   rm -f ~/.config/lm-studio/auth_token
   ```

3. Restart the tray manager:

   ```bash
   ./lmstudio_autostart.sh
   ```

4. Verify daemon is running with fresh authentication:

   ```bash
   lms ps
   # Should show no authentication errors
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

3. Install missing GTK packages.  The tray uses
   the AppIndicator3 API which is provided by the
   `gir1.2-ayatanaappindicator3-0.1` package on Debian/Ubuntu-based
   systems; some distributions expose the API simply as
   `AppIndicator3`.  The code will now automatically fall back to the
   alternate namespace if necessary, but you still need the GIR
   typelib installed.

   ```bash
   sudo apt install gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
   ```

4. Check logs:

   ```bash
   grep -i "error\|icon\|tray" .logs/lmstudio_tray.log
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
