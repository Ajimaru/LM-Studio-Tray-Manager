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

- **Bash**
  - Website: <https://www.gnu.org/software/bash/>
  - License: GPL-3.0-or-later

- **LM Studio / llmster / lms CLI**
  - Website: <https://lmstudio.ai/>
  - License: See vendor terms and licensing documentation

## Build-time Python Dependencies

These packages are used to create the standalone binary via PyInstaller.

- **PyInstaller 6.19.0**
  - Website: <https://pyinstaller.org/>
  - License: GPL-2.0-or-later with bootloader exception (allows bundling proprietary applications)

- **altgraph 0.17.5**
  - Website: <https://pypi.org/project/altgraph/>
  - License: MIT License

- **pyinstaller-hooks-contrib 2026.1**
  - Website: <https://github.com/pyinstaller/pyinstaller-hooks-contrib>
  - License: GPL-2.0-or-later OR Apache-2.0

- **setuptools 82.0.0**
  - Website: <https://github.com/pypa/setuptools>
  - License: MIT License

- **packaging 26.0**
  - Website: <https://github.com/pypa/packaging>
  - License: BSD-2-Clause OR Apache-2.0

- **rumps 0.4.0** (macOS only - not used in Linux builds)
  - Website: <https://github.com/jaredks/rumps>
  - License: BSD-3-Clause

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
