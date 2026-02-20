# LM Studio Automation

![LM Studio Icon](assets/img/lm-studio-64x64.png)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10-blue.svg)](https://www.python.org/downloads/)
[![LM Studio App](https://img.shields.io/badge/LM_Studio_App-v0.4.3+-green.svg)](https://lmstudio.ai/download)
[![LM Studio Daemon v0.0.3+](https://img.shields.io/badge/LM_Studio_Daemon-v0.0.3+-green.svg)](https://lmstudio.ai)
[![Made with Love in 🇪🇺](https://img.shields.io/badge/Made_with_❤️_in_🇪🇺-gray.svg)](https://europa.eu/)

Automation scripts for LM Studio – a powerful desktop and server application for running Large Language Models locally on consumer hardware.

## Features

- **Daemon Automation** (`lmstudio_autostart.sh`): Automatically start the LM Studio daemon, wait for API availability, and optionally load models
- **System Tray Monitor** (`lmstudio_tray.py`): GTK3 system tray integration with real-time model status monitoring (🟢🟡🔴), daemon control, and desktop app launcher with live status indicators
- **Smart Status Indicators**: Real-time status display for daemon and desktop app (🟢 running / 🟡 stopped / 🔴 not found)
- **Desktop App Launcher**: One-click option in tray to start LM Studio desktop GUI (supports both .deb and AppImage), automatically ensuring daemon is running
- **GUI Integration**: Support for launching the LM Studio desktop GUI while managing daemon lifecycle
- **Flexible Model Management**: Interactive model selection, automatic model loading, and status tracking

## Getting Started

After cloning the repository, follow these steps to set up the automation environment:

### 1. Run the Setup Script

```bash
./setup.sh
```

This comprehensive setup script:

- ✓ Checks for LM Studio daemon (llmster) – installs if missing
- ✓ Checks for LM Studio desktop app – intelligently detects .deb or AppImage
- ✓ Checks for Python 3.10 – installs via apt if missing
- ✓ Creates Python 3.10 virtual environment with PyGObject/GTK3 support

The script will guide you through interactive setup steps if needed.

### 2. Run the Automation Script

```bash
# Start the LM Studio daemon and system tray monitor
./lmstudio_autostart.sh
```

The script will:

- Check and install system dependencies (curl, notify-send, python3)
- Start the LM Studio daemon
- Wait for the API to be available
- Launch the system tray monitor in the background

### 3. Verify It Works

- Check that the LM Studio daemon is running: `lms ps`
- Look for the system tray icon (should appear in your taskbar)
- Check setup log: `cat .logs/setup.log`
- Check daemon log: `tail -f .logs/lmstudio_autostart.log`

## Project Structure

```files
.
├── setup.sh                    # 👈 Run this FIRST after cloning
├── lmstudio_autostart.sh       # Main automation script
├── lmstudio_tray.py            # System tray monitor
├── docs/
│   ├── index.html              # Full documentation (open in browser)
│   ├── VENV_SETUP.md           # Virtual environment guide
│   └── README.md               # Docs overview
├── .logs/                      # Log files (created automatically)
│   ├── lmstudio_autostart.log
│   └── lmstudio_tray.log
├── venv/                       # Virtual environment (created by setup.sh)
├── README.md                   # This file
└── LICENSE                     # MIT License
```

## Quick Reference

```bash
# First time setup
./setup.sh

# Start daemon with defaults
./lmstudio_autostart.sh

# Start daemon and load a specific model
./lmstudio_autostart.sh --model qwen2.5:7b-instruct

# Launch GUI (stops daemon first)
./lmstudio_autostart.sh --gui

# Interactive model selection
./lmstudio_autostart.sh --list-models

# Debug mode with verbose output
./lmstudio_autostart.sh --debug

# Check daemon status
lms ps

# Stop daemon manually
lms daemon down
```

## Troubleshooting

### WebSocket Authentication Error

If you encounter the error `Invalid passkey for lms CLI client`, this is typically caused by stale daemon processes. The script automatically handles this by:

- Cleaning up old daemon processes on startup
- Clearing stale authentication tokens
- Restarting the daemon fresh

The fix runs automatically when you start the script. Check the logs if issues persist:

```bash
cat .logs/lmstudio_autostart.log
cat .logs/lmstudio_tray.log
```

## Documentation

- **[Full Documentation](docs/index.html)** – Detailed usage examples, flow diagrams, and architecture
- **[Virtual Environment Setup](docs/VENV_SETUP.md)** – Guide for Python environment configuration and troubleshooting

## Requirements

- **LM Studio Daemon** (llmster v0.0.3+): Headless backend for model inference
- **Python 3** with PyGObject (for GTK3 system tray)
- **Bash 5+** for automation scripts
- Linux system with GNOME/GTK3 support (Pop!_OS, Ubuntu, Fedora, etc.)

## Official Resources

- [LM Studio Blog](https://lmstudio.ai/blog) – Latest updates and announcements
- [LM Studio Documentation](https://lmstudio.ai/docs/app) – Complete API and feature documentation
- [LM Studio Download](https://lmstudio.ai/download) – Get the latest version

## License

MIT License – See [LICENSE](LICENSE) file for details

---

**Note:** These automation scripts are designed for the daemon workflow. Make sure the LM Studio daemon is properly installed and the `lms` CLI is available in your PATH.
