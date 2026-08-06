# Third-Party Licenses

This project depends on third-party software at development time and runtime.

This file is a practical reference for maintainers and users. It is not legal advice.

## Runtime / System Dependencies

- **Python**
  - Website: <https://www.python.org/>
  - License: Python Software Foundation License

- **PyGObject**
  - Website: <https://pygobject.readthedocs.io/>
  - License: LGPL-2.1-or-later

- **GTK 3 (via GObject Introspection bindings)**
  - Website: <https://www.gtk.org/>
  - License: LGPL-2.1-or-later

- **pystray 0.19.5** (Windows only - notification-area icon and menu)
  - Website: <https://github.com/moses-palmer/pystray>
  - License: LGPL-3.0-or-later

- **Pillow 12.3.0** (Windows only - required by pystray for the tray image)
  - Website: <https://python-pillow.github.io/>
  - License: MIT-CMU

- **six 1.17.0** (Windows only - transitive dependency of pystray)
  - Website: <https://github.com/benjaminp/six>
  - License: MIT

- **Tcl/Tk (via the `tkinter` standard library module)** (Windows dialogs)
  - Website: <https://www.tcl.tk/>
  - License: TCL/TK License (BSD-style)

- **Bash**
  - Website: <https://www.gnu.org/software/bash/>
  - License: GPL-3.0-or-later

- **Windows PowerShell / PowerShell**
  - Website: <https://learn.microsoft.com/powershell/>
  - License: MIT (PowerShell 7+); Windows PowerShell 5.1 ships with Windows
    under the Windows license terms

- **LM Studio / llmster / lms CLI**
  - Website: <https://lmstudio.ai/>
  - License: See vendor terms and licensing documentation

## Build-time Python Dependencies

These packages are used to create the standalone binary via PyInstaller.

- **PyInstaller 6.21.0**
  - Website: <https://pyinstaller.org/>
  - License: GPL-2.0-or-later with bootloader exception (allows bundling proprietary applications)

- **altgraph 0.17.5**
  - Website: <https://pypi.org/project/altgraph/>
  - License: MIT License

- **pyinstaller-hooks-contrib 2026.6**
  - Website: <https://github.com/pyinstaller/pyinstaller-hooks-contrib>
  - License: GPL-2.0-or-later OR Apache-2.0

- **setuptools 83.0.0**
  - Website: <https://github.com/pypa/setuptools>
  - License: MIT License

- **packaging 26.2**
  - Website: <https://github.com/pypa/packaging>
  - License: Apache-2.0 OR BSD-2-Clause

- **certifi 2026.7.22** (bundled into the binary for HTTPS update checks)
  - Website: <https://github.com/certifi/python-certifi>
  - License: MPL-2.0

- **macholib 1.16.4** (used by PyInstaller on macOS)
  - Website: <https://github.com/ronaldoussoren/macholib>
  - License: MIT License

- **pefile 2024.8.26** (used by PyInstaller on Windows)
  - Website: <https://github.com/erocarrera/pefile>
  - License: MIT License

- **pywin32-ctypes 0.2.3** (used by PyInstaller on Windows)
  - Website: <https://github.com/enthought/pywin32-ctypes>
  - License: BSD-3-Clause

- **rumps 0.4.0** (macOS only - not used in Linux or Windows builds)
  - Website: <https://github.com/jaredks/rumps>
  - License: BSD-3-Clause

## Packaging Tools

- **Inno Setup 6** (optional - builds the Windows installer)
  - Website: <https://jrsoftware.org/isinfo.php>
  - License: Modified BSD; the compiler is a build tool and is not
    redistributed with this project

## Development / CI Dependencies

The repository also uses GitHub Actions workflows and community actions under `.github/workflows/*`.
Their licenses and terms are governed by each upstream action repository and GitHub Terms.

Current workflow actions include (non-exhaustive):

- `actions/checkout`
- `actions/setup-python`
- `DavidAnson/markdownlint-cli2-action`
- `lycheeverse/lychee-action`
- `github/codeql-action`
- `gitleaks/gitleaks-action`

Please review each action repository for exact license details.

## Notes

- System package licenses may vary by distribution packaging.
- Build-time dependencies are listed with their licenses for reference; bundled binaries may inherit additional obligations.
- If you redistribute binaries or bundled dependencies, ensure full license text and notice requirements are met.
- Revisit this file when adding new runtime, build-time dependencies, or workflow actions.
