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
- If you redistribute binaries or bundled dependencies, ensure full license text and notice requirements are met.
- Revisit this file when adding new runtime dependencies or workflow actions.
