# LM-Studio-Tray-Manager

![LM Studio Icon](assets/img/lm-studio-tray-manager.svg)

Automation scripts for LM Studio & llmster - to control and monitor the applications from the system tray.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10](https://img.shields.io/badge/Python-3.10-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/Platform-Linux-orange.svg)](https://www.linux.org/)
[![LM Studio App v0.4.3+](https://img.shields.io/badge/LM_Studio_App-v0.4.3+-green.svg)](https://lmstudio.ai/download)
[![llmster v0.0.3+](https://img.shields.io/badge/llmster-v0.0.3+-green.svg)](https://lmstudio.ai)
[![Release](https://img.shields.io/github/v/release/Ajimaru/LM-Studio-Tray-Manager)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/Ajimaru/LM-Studio-Tray-Manager/total.svg)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/releases)

---

## Features

- **🖥️ System Tray Monitor**: GTK3 tray integration with live daemon/app controls and status transitions
- **🎛️ Tray Menu Controls**: Start/stop daemon and start/stop desktop app, including conflict-safe switching between both modes
- **🚦 Icon Status Schema**: `❌` not installed, `⚠️` both stopped, `ℹ️` runtime active but no model loaded, `✅` model loaded
- **🔎 Update Checks**: Periodic GitHub release checks with a manual "Check for updates" action under the Options menu

## Screenshots

<!-- markdownlint-disable MD033 -->

<img src="assets/img/tray-menu.png" alt="Tray Menu" style="width:25%;" />

<!-- markdownlint-enable MD033 -->

## Getting Started

### User Installation (from Release)

**1.** Open the latest release:

```text
https://github.com/Ajimaru/LM-Studio-Tray-Manager/releases/latest
```

**2.** Choose your installation path:

#### Path 1 (Recommended): Binary release

<!-- markdownlint-disable MD033 -->
<details>
<summary>Show Binary release install steps</summary>

**Download:**

- `LM-Studio-Tray-Manager-vX.Y.Z-binary.tar.gz`

**Extract and run:**

```bash
tar -xzf LM-Studio-Tray-Manager-vX.Y.Z-binary.tar.gz
cd LM-Studio-Tray-Manager-vX.Y.Z-binary

./setup.sh
./lmstudio-tray-manager -a
```

**Note:** The setup script detects the binary release and skips Python virtual environment creation (all dependencies are already bundled in the binary).

**Verify:**

- `lms ps`
- tray icon appears
- `tail -f .logs/lmstudio_tray.log`

</details>
<!-- markdownlint-enable MD033 -->

#### Path 2 (Python package)

<!-- markdownlint-disable MD033 -->
<details>
<summary>Show Python install steps</summary>

**Download:**

- `LM-Studio-Tray-Manager-vX.Y.Z.tar.gz`

**Extract and run:**

```bash
tar -xzf LM-Studio-Tray-Manager-vX.Y.Z.tar.gz
cd LM-Studio-Tray-Manager-vX.Y.Z

./setup.sh
./lmstudio_autostart.sh
```

This setup script:

- ✓ Checks for LM Studio daemon (llmster)
- ✓ Checks for LM Studio desktop app - intelligently detects .deb or AppImage
- ✓ Checks for Python 3.10 - installs via apt if missing
- ✓ Creates Python 3.10 virtual environment with PyGObject/GTK3 support

**Verify:**

- `lms ps`
- tray icon appears
- `tail -f .logs/lmstudio_autostart.log`
- `tail -f .logs/lmstudio_tray.log`

</details>
<!-- markdownlint-enable MD033 -->

## Requirements

- **LM Studio Daemon** (llmster v0.0.3+): Headless backend for model inference
- **LM Studio Desktop App** (v0.4.3+): GUI frontend for model management and interaction
- **Python 3.10** with PyGObject (for GTK3 system tray)
- Linux system with GNOME/GTK3 support (Pop!_OS, Ubuntu, Fedora, etc.)

## Quick Reference

<!-- markdownlint-disable MD033 -->
<details>
<summary>Click to expand</summary>

```bash
# First time setup
./setup.sh

# Preview setup actions (no changes)
./setup.sh --dry-run

# Setup script options
./setup.sh --help

# Start daemon with defaults
./lmstudio_autostart.sh

# Launch GUI (stops daemon first) - long or short form
./lmstudio_autostart.sh --gui
./lmstudio_autostart.sh -g

# Interactive model selection (loads selected model)
./lmstudio_autostart.sh --list-models

# Debug mode with verbose output - long or short form
./lmstudio_autostart.sh --debug
./lmstudio_autostart.sh -d

# Run the binary (release package) and daemon - long or short form
./lmstudio-tray-manager --auto-start-daemon
./lmstudio-tray-manager -a

# Start the GUI directly via the binary - long or short form
./lmstudio-tray-manager --gui
./lmstudio-tray-manager -g

# Version and help - long or short form
./lmstudio-tray-manager --version
./lmstudio-tray-manager -v
./lmstudio-tray-manager --help
./lmstudio-tray-manager -h

# Debug mode (binary) - long or short form
./lmstudio-tray-manager --debug
./lmstudio-tray-manager -d

# Combine short flags
./lmstudio-tray-manager -d -a   # debug + auto-start daemon
./lmstudio-tray-manager -dg     # debug + gui
./lmstudio-tray-manager -dga    # debug + gui + auto-start-daemon; note: -a is ignored when -g is active

# Check daemon status
lms ps

# Stop daemon manually
lms daemon down
```

</details>
<!-- markdownlint-enable MD033 -->

## Troubleshooting

For comprehensive troubleshooting guidance:

- **Setup issues**: See [SETUP.md](docs/SETUP.md)
- **Runtime issues**: See [USE.md](docs/USE.md)
- **Build problems**: See [BUILD.md](docs/BUILD.md)
- **WebSocket Authentication Error**: See [USE.md - WebSocket Authentication Error](docs/USE.md#websocket-authentication-error)

Check the logs if issues persist:

```bash
cat .logs/setup.log
cat .logs/lmstudio_autostart.log
cat .logs/lmstudio_tray.log
```

## Documentation

- [Readme](docs/README.md) - Documentation overview and quick links
- [Docs Landing Page](docs/index.html) - GitHub Pages entry point with links to all docs

[![Docs](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/docs.yml/badge.svg)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/docs.yml)

## Security & Community

- [Security Policy](SECURITY.md) - Supported versions, reporting, and response process
- [Code of Conduct](CODE_OF_CONDUCT.md) - Expected behavior for contributors
- [Third-Party Licenses](THIRD_PARTY_LICENSES.md) - Overview of external runtime and CI dependencies

[![Codacy Badge](https://app.codacy.com/project/badge/Grade/008764f58bb046ef886c86bccd336b85)](https://app.codacy.com/gh/Ajimaru/LM-Studio-Tray-Manager/dashboard?utm_source=gh&utm_medium=referral&utm_content=&utm_campaign=Badge_grade)
[![CI](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/ci.yml/badge.svg)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/ci.yml)
[![Security](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/security.yml/badge.svg)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/security.yml)
[![Bandit](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/bandit.yml/badge.svg)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/bandit.yml)
[![CodeQL](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/codeql.yml/badge.svg)](https://github.com/Ajimaru/LM-Studio-Tray-Manager/actions/workflows/codeql.yml)

## Project Meta

- **[Changelog](CHANGELOG.md)** - Notable project changes by release
- **[Contributing Guide](CONTRIBUTING.md)** - How to contribute and validate changes
- **[Authors](AUTHORS)** - Project contributors displayed in the About dialog

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
