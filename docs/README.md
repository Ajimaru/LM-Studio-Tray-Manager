# Documentation

Welcome to the LM Studio Automation documentation.

## Quick Links

- **[Main Documentation](index.html)** – Start here for full usage guide, examples, and architecture
- **[Virtual Environment Setup](VENV_SETUP.md)** – How to configure the Python environment

## File Organization

```files
docs/
├── index.html              # Main comprehensive documentation (open in browser)
├── VENV_SETUP.md           # Virtual environment configuration guide
└── README.md               # This file
```

## Getting Help

If you encounter issues:

1. Check **[index.html](index.html)** for troubleshooting sections
2. Review **[VENV_SETUP.md](VENV_SETUP.md)** for environment-specific issues
3. Check the log files in the `.logs` directory from the project root:
   - `.logs/setup.log` – Setup script installation log
   - `.logs/lmstudio_autostart.log` – Daemon and startup logs
   - `.logs/lmstudio_tray.log` – System tray monitor logs

## Opening the Documentation

The `index.html` is best viewed in a web browser. You can open it with:

```bash
# From the repository root
xdg-open docs/index.html        # On Linux
open docs/index.html            # On macOS
start docs\index.html           # On Windows
```

Or browse it directly if you're viewing this on GitHub:
<https://github.com/Ajimaru/LM-Studio/blob/main/docs/index.html>
