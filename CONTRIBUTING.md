# Contributing

Thanks for contributing to LM-Studio.

## Quick Start

1. Fork and clone the repository.
2. Run setup:

```bash
./setup.sh
```

Optional checks:

```bash
./setup.sh --dry-run
./setup.sh --help
```

3. Start the default runtime flow:

```bash
./lmstudio_autostart.sh
```

## Development Guidelines

- Keep changes focused and minimal.
- Preserve existing behavior unless the change explicitly targets behavior updates.
- Follow the current style of each file (Bash/Python/HTML/Markdown).
- For Python, keep lines readable and prefer existing patterns used in `lmstudio_tray.py`.
- Update documentation when behavior or CLI options change.

## Typical Contribution Areas

- Tray UX and status handling (`lmstudio_tray.py`)
- Startup orchestration (`lmstudio_autostart.sh`)
- Setup flow (`setup.sh`)
- Documentation (`docs/` and `README.md`)

## Commit & PR Guidance

- Use clear commit messages in imperative style.
  - Example: `Add dry-run mode to setup.sh`
- Reference related issues in PR descriptions.
- Include a short test/verification section in each PR, e.g.:
  - `bash -n setup.sh`
  - manual tray action checks
  - docs link checks

## Documentation Expectations

If you change setup or runtime behavior, update at least:

- `README.md`
- `docs/guide.html`
- `docs/SETUP.md`

## Code of Conduct & Security

Please follow:

- `CODE_OF_CONDUCT.md`
- `SECURITY.md`
