# Privacy Policy

**Last updated: 2026-09-05**

LM Studio Tray Manager does not collect, store, or transmit any personal
data. There is no telemetry, no analytics, and no user account.

## What the application stores

All data stays on your computer. Nothing is sent to the developer.

| Data | Location | Purpose |
| --- | --- | --- |
| Settings (API host and port, display preferences) | `%APPDATA%\lmstudio_tray.json` (Windows), `~/.config/lmstudio_tray.json` (Linux/macOS) | Remembering your configuration between sessions |
| Log files | `%LOCALAPPDATA%\lmstudio-tray-manager` (Windows), `~/.local/share/lmstudio-tray-manager` (Linux/macOS), or a `.logs` folder next to the executable when that location is writable | Diagnosing problems locally |

You can delete both at any time. Uninstalling the application removes its
log files.

## Network connections

The application makes exactly two kinds of network requests:

1. **To your local LM Studio installation** (`http://localhost:1234` by
   default, configurable). This is a connection to software running on your
   own computer, used to read the daemon's status and to start or stop it.
   No data leaves your machine.
2. **To the GitHub API** (`https://api.github.com`), to check whether a
   newer release of this application is available. This request sends no
   personal data. As with any HTTP request, GitHub receives your IP address
   and the request itself; see the
   [GitHub Privacy Statement](https://docs.github.com/site-policy/privacy-policies/github-privacy-statement)
   for how GitHub handles that. The update check runs when the application
   starts and when you trigger it manually from the menu.

The application does not connect to any server operated by the developer,
because there is none.

## Third-party software

LM Studio Tray Manager controls [LM Studio](https://lmstudio.ai), a separate
application by a different vendor. LM Studio has its own privacy policy,
which governs anything LM Studio itself does. This application only starts,
stops, and reads the status of that software.

## Changes to this policy

Any change will be published on this page with an updated date above. The
full history is visible in the
[repository](https://github.com/Ajimaru/LM-Studio-Tray-Manager).

## Contact

Questions about this policy can be raised as an issue in the
[GitHub repository](https://github.com/Ajimaru/LM-Studio-Tray-Manager/issues).
