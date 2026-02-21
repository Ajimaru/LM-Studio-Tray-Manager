# LM-Studio-Tray-Manager

![LM Studio Icon](assets/img/lm-studio-tray-manager.svg)

---

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10](https://img.shields.io/badge/Python-3.10-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/Platform-Linux-orange.svg)](https://www.linux.org/)
[![LM Studio App v0.4.3+](https://img.shields.io/badge/LM_Studio_App-v0.4.3+-green.svg)](https://lmstudio.ai/download)
[![LM Studio Daemon v0.0.3+](https://img.shields.io/badge/LM_Studio_Daemon-v0.0.3+-green.svg)](https://lmstudio.ai)

[![Release](https://img.shields.io/github/v/release/Ajimaru/LM-Studio-Tray-Manager)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/Ajimaru/LM-Studio-Tray-Manager/total.svg)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/releases)

Automation scripts for LM Studio - a powerful desktop and server application for running Large Language Models locally on consumer hardware.

## Features

- **⚙️ Daemon/Desktop Orchestration** (`lmstudio_autostart.sh`): Default mode starts `llmster` + tray monitor; `--gui` stops daemon first, then starts desktop app + tray monitor
- **🖥️ System Tray Monitor** (`lmstudio_tray.py`): GTK3 tray integration with live daemon/app controls and status transitions
- **🎛️ Tray Menu Controls**: Start/stop daemon and start/stop desktop app, including conflict-safe switching between both modes
- **🚦 Icon Status Schema**: `❌` not installed, `⚠️` both stopped, `ℹ️` runtime active but no model loaded, `✅` model loaded
- **🛡️ Robust Runtime Handling**: Cooldown guard against double-click actions and best-effort process stop fallbacks
- **🧠 Interactive Model Selection**: Choose from local models via `--list-models` and auto-load the selection in daemon mode
- **🧰 Comprehensive Setup Script** (`setup.sh`): Checks for and installs dependencies, sets up Python environment, and provides a `--dry-run` option for previewing actions without making changes

## Getting Started

### User Installation (from Release)

1. Open the latest release:

```text
https://github.com/Ajimaru/LM-Studio-Tray-Manager/releases/latest
```

2. Download one of these artifacts:

- `LM-Studio-Tray-Manager-latest.tar.gz`
- `LM-Studio-Tray-Manager-latest.zip`

3. Extract and enter the folder.

Example (`.tar.gz`):

```bash
tar -xzf LM-Studio-Tray-Manager-latest.tar.gz
cd LM-Studio-Tray-Manager-vX.Y.Z
```

4. Run the Setup Script

```bash
./setup.sh

# Preview setup actions without changing system state
./setup.sh --dry-run
```

**Note:** If you installed from a release archive, run these commands inside the extracted release directory.

This setup script:

- ✓ Checks for LM Studio daemon (llmster)
- ✓ Checks for LM Studio desktop app - intelligently detects .deb or AppImage
- ✓ Checks for Python 3.10 - installs via apt if missing
- ✓ Creates Python 3.10 virtual environment with PyGObject/GTK3 support

5. Run the Automation Script

```bash
# Start the LM Studio daemon and system tray monitor
./lmstudio_autostart.sh
```

The script will:

- Check and install system dependencies (curl, notify-send, python3)
- Start `llmster` daemon (default mode)
- Launch the system tray monitor in the background

6. Verify It Works

- Check that the LM Studio daemon is running: `lms ps`
- Look for the system tray icon (should appear in your taskbar)
- Check setup log: `cat .logs/setup.log`
- Check daemon log: `tail -f .logs/lmstudio_autostart.log`
- Check tray log: `tail -f .logs/lmstudio_tray.log`

## Requirements

- **LM Studio Daemon** (llmster v0.0.3+): Headless backend for model inference
- **Python 3** with PyGObject (for GTK3 system tray)
- **Bash 5+** for automation scripts
- Linux system with GNOME/GTK3 support (Pop!_OS, Ubuntu, Fedora, etc.)

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

# Interactive model selection (loads selected model)
./lmstudio_autostart.sh --list-models

# Start and load a specific model key
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

[![Docs](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/docs.yml/badge.svg)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/docs.yml)

## Security & Community

- **[Security Policy](SECURITY.md)** - Supported versions, reporting, and response process
- **[Code of Conduct](CODE_OF_CONDUCT.md)** - Expected behavior for contributors
- **[Third-Party Licenses](THIRD_PARTY_LICENSES.md)** - Overview of external runtime and CI dependencies

[![Codacy Badge](https://app.codacy.com/project/badge/Grade/008764f58bb046ef886c86bccd336b85)](https://app.codacy.com/gh/Ajimaru/LM-Studio-Tray-Manager/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)
[![CI](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/ci.yml/badge.svg)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/ci.yml)
[![Security](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/security.yml/badge.svg)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/security.yml)
[![Bandit](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/bandit.yml/badge.svg)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/bandit.yml)
[![CodeQL](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/codeql.yml/badge.svg)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/codeql.yml)

## Project Meta

- **[Changelog](CHANGELOG.md)** - Notable project changes by release
- **[Contributing Guide](CONTRIBUTING.md)** - How to contribute and validate changes

[![Last Commit](https://img.shields.io/github/last-commit/Ajimaru/LM-Studio-Tray-Manager)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/commits/main)
[![Issues](https://img.shields.io/github/issues/Ajimaru/LM-Studio-Tray-Manager)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/issues)
[![Contributors](https://img.shields.io/github/contributors/Ajimaru/LM-Studio-Tray-Manager)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/graphs/contributors)

## Official Resources

- [LM Studio Blog](https://lmstudio.ai/blog) - Latest updates and announcements
- [LM Studio Documentation](https://lmstudio.ai/docs/app) - Complete API and feature documentation
- [LM Studio Download](https://lmstudio.ai/download) - Get the latest version

## License

MIT License - See [LICENSE](LICENSE) file for details

---

[![Stars](https://img.shields.io/github/stars/Ajimaru/LM-Studio-Tray-Manager?style=social)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/stargazers)
[![Forks](https://img.shields.io/github/forks/Ajimaru/LM-Studio-Tray-Manager?style=social)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/network/members)
[![Watchers](https://img.shields.io/github/watchers/Ajimaru/LM-Studio-Tray-Manager?style=social)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/watchers)
[![Made with Love in 🇪🇺](https://img.shields.io/badge/Made_with_❤️_in_🇪🇺-gray.svg)](https://europa.eu/)
