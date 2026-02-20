# LM Studio Automation

![LM Studio Icon](assets/img/lm-studio-64x64.png)

---

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10-blue.svg)](https://www.python.org/downloads/)
[![LM Studio App](https://img.shields.io/badge/LM_Studio_App-v0.4.3+-green.svg)](https://lmstudio.ai/download)
[![LM Studio Daemon v0.0.3+](https://img.shields.io/badge/LM_Studio_Daemon-v0.0.3+-green.svg)](https://lmstudio.ai)
[![CI](https://github.com/Ajimaru/LM-Studio/actions/workflows/ci.yml/badge.svg)](https://github.com/Ajimaru/LM-Studio/actions/workflows/ci.yml)
[![Docs](https://github.com/Ajimaru/LM-Studio/actions/workflows/docs.yml/badge.svg)](https://github.com/Ajimaru/LM-Studio/actions/workflows/docs.yml)
[![Security](https://github.com/Ajimaru/LM-Studio/actions/workflows/security.yml/badge.svg)](https://github.com/Ajimaru/LM-Studio/actions/workflows/security.yml)
[![Codacy Badge](https://app.codacy.com/project/badge/Grade/008764f58bb046ef886c86bccd336b85)](https://app.codacy.com/gh/Ajimaru/LM-Studio/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)
[![Made with Love in 🇪🇺](https://img.shields.io/badge/Made_with_❤️_in_🇪🇺-gray.svg)](https://europa.eu/)

Automation scripts for LM Studio - a powerful desktop and server application for running Large Language Models locally on consumer hardware.

## Features

- **⚙️ Daemon/Desktop Orchestration** (`lmstudio_autostart.sh`): Default mode starts `llmster` + tray monitor; `--gui` stops daemon first, then starts desktop app + tray monitor
- **🖥️ System Tray Monitor** (`lmstudio_tray.py`): GTK3 tray integration with live daemon/app controls and status transitions
- **🎛️ Tray Menu Controls**: Start/stop daemon and start/stop desktop app, including conflict-safe switching between both modes
- **🚦 Icon Status Schema**: `❌` not installed, `⚠️` both stopped, `ℹ️` runtime active but no model loaded, `✅` model loaded
- **🛡️ Robust Runtime Handling**: Cooldown guard against double-click actions and best-effort process stop fallbacks
- **🧠 Interactive Model Selection**: Optional model selection via `--list-models`
- **🧰 Comprehensive Setup Script** (`setup.sh`): Checks for and installs dependencies, sets up Python environment, and provides a `--dry-run` option for previewing actions without making changes

## Getting Started

After cloning the repository, follow these steps to set up the automation environment:

### 1. Run the Setup Script

```bash
./setup.sh

# Preview setup actions without changing system state
./setup.sh --dry-run
```

This comprehensive setup script:

- ✓ Checks for LM Studio daemon (llmster)
- ✓ Checks for LM Studio desktop app - intelligently detects .deb or AppImage
- ✓ Checks for Python 3.10 - installs via apt if missing
- ✓ Creates Python 3.10 virtual environment with PyGObject/GTK3 support

Available setup options:

- `./setup.sh --dry-run` (or `-n`): show planned actions without making changes
- `./setup.sh --help` (or `-h`): show setup options

The script will guide you through interactive setup steps if needed.

### 2. Run the Automation Script

```bash
# Start the LM Studio daemon and system tray monitor
./lmstudio_autostart.sh
```

The script will:

- Check and install system dependencies (curl, notify-send, python3)
- Start `llmster` daemon (default mode)
- Launch the system tray monitor in the background

### 3. Verify It Works

- Check that the LM Studio daemon is running: `lms ps`
- Look for the system tray icon (should appear in your taskbar)
- Check setup log: `cat .logs/setup.log`
- Check daemon log: `tail -f .logs/lmstudio_autostart.log`

## Quick Reference

```bash
# First time setup
./setup.sh

# Preview setup actions (no changes)
./setup.sh --dry-run

# Show setup options
./setup.sh --help

# Start daemon with defaults
./lmstudio_autostart.sh

# Launch GUI (stops daemon first)
./lmstudio_autostart.sh --gui

# Interactive model selection
./lmstudio_autostart.sh --list-models

# Start with model label for tray/status context
./lmstudio_autostart.sh --model qwen2.5:7b-instruct

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

- **[Docs Landing Page](docs/index.html)** - GitHub Pages entry point with links to all docs
- **[Full Documentation](docs/guide.html)** - Detailed usage examples, flow diagrams, and architecture
- **[Setup Guide](docs/SETUP.md)** - Complete setup.sh guide, Python environment configuration, and troubleshooting
- **[Python Docstrings Reference](docs/python_docstrings.html)** - Static API-style view of `lmstudio_tray.py` docstrings

## Requirements

- **LM Studio Daemon** (llmster v0.0.3+): Headless backend for model inference
- **Python 3** with PyGObject (for GTK3 system tray)
- **Bash 5+** for automation scripts
- Linux system with GNOME/GTK3 support (Pop!_OS, Ubuntu, Fedora, etc.)

## Security & Community

- **[Security Policy](SECURITY.md)** - Supported versions, reporting, and response process
- **[Code of Conduct](CODE_OF_CONDUCT.md)** - Expected behavior for contributors
- **[Third-Party Licenses](THIRD_PARTY_LICENSES.md)** - Overview of external runtime and CI dependencies

## Project Meta

- **[Changelog](CHANGELOG.md)** - Notable project changes by release
- **[Contributing Guide](CONTRIBUTING.md)** - How to contribute and validate changes

## Official Resources

- [LM Studio Blog](https://lmstudio.ai/blog) - Latest updates and announcements
- [LM Studio Documentation](https://lmstudio.ai/docs/app) - Complete API and feature documentation
- [LM Studio Download](https://lmstudio.ai/download) - Get the latest version

## License

MIT License - See [LICENSE](LICENSE) file for details

---

**Note:** These automation scripts support both daemon-first and GUI-first workflows. Ensure `llmster`/`lms` and LM Studio desktop app are installed.
