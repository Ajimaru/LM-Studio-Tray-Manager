# Documentation

Welcome to the LM-Studio-Tray-Manager documentation.

## Quick Links

- **[Landing Page](index.html)** - GitHub Pages start page with links to all documentation formats
- **[Full HTML Guide](guide.html)** - Detailed usage guide, flow diagrams, and architecture
- **[Build Guide](BUILD.md)** - PyInstaller build and runtime requirements
- **[Setup Guide](SETUP.md)** - Complete setup.sh and Python environment guide
- **[Usage Guide](USE.md)** - Application usage, CLI options, system tray interface, and troubleshooting
- **[Python API Reference](mkdocs/index.html)** - Interactive API documentation generated from `lmstudio_tray.py` with MkDocs
- **[Third-Party Licenses](../THIRD_PARTY_LICENSES.md)** – Overview of external runtime and CI dependencies

## File Organization

```files
docs/
├── index.html              # GitHub Pages landing page
├── guide.html              # Main comprehensive documentation (full guide)
├── BUILD.md                # Binary build and runtime guide
├── SETUP.md                # Comprehensive setup and environment guide
├── USE.md                  # Application usage, CLI options, system tray interface, and troubleshooting
├── mkdocs/                 # MkDocs-generated Python API reference
│   └── index.html          # API documentation entry point
└── README.md               # This file
```

## Getting Help

If you encounter issues:

1. Runtime/tray issues: **[USE.md](USE.md)** (includes log viewing and common failures)
2. Setup/venv/Python issues: **[SETUP.md](SETUP.md)**
3. Build/PyInstaller issues: **[BUILD.md](BUILD.md)**
4. Logs (project root `.logs/`):
   - `.logs/setup.log` - Setup script installation log
   - `.logs/lmstudio_autostart.log` - Daemon and startup logs
   - `.logs/lmstudio_tray.log` - Tray monitor logs

## Opening the Documentation

The `index.html` is best viewed in a web browser. You can open it with:

```bash
# From the repository root
xdg-open docs/index.html        # On Linux
open docs/index.html            # On macOS
start docs\index.html           # On Windows
```

Or browse it directly if you're viewing this on GitHub:
<https://github.com/Ajimaru/LM-Studio-Tray-Manager/blob/main/docs/index.html>
