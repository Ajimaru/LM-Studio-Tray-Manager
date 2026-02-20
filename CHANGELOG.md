# Changelog

All notable changes to this project are documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic Versioning where practical.

## [0.1.0] - 2026-02-20

### Added

- `setup.sh`: Added `--dry-run` (`-n`) to preview setup actions without applying system changes.
- `setup.sh`: Added `--help` (`-h`) option.
- `lmstudio_tray.py`: Added an **About** menu entry in the tray menu.
- `lmstudio_tray.py`: About dialog now shows branding metadata and model context.
- Added central `VERSION` file and wired tray version display to read from it.
- Documentation updates for setup flow and dry-run usage across docs.
- Renamed setup documentation from `docs/VENV_SETUP.md` to `docs/SETUP.md`.
- Initial centralized version metadata (`VERSION`).
- Tray About dialog with application and repository information

### Changed

- Documentation wording aligned from venv-centric labels to setup/environment-centric terminology.
- Internal docs links and workflow checks updated to `docs/SETUP.md`.

### Fixed

- Consistency fixes for setup documentation links and references.

---

For release tags and history, see the repository tags and pull requests.
