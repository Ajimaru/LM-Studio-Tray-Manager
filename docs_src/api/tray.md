# System Tray Implementation

System tray icon implementations with status monitoring: GTK3 on Linux,
rumps on macOS, pystray on Windows. All three expose the same status
vocabulary and menu actions.

## Linux/GTK3 Tray

::: lmstudio_tray.TrayIcon
    options:
      show_root_heading: true
      show_source: true
      members: true
      group_by_category: true

## macOS Tray

::: lmstudio_tray.MacOSTrayIcon
    options:
      show_root_heading: true
      show_source: true
      members: true
      group_by_category: true

## Windows Tray

The notification area shows an icon but no text, so the status emoji lives
in the tooltip rather than in a title. pystray provides neither timers nor
dialogs: the periodic checks run on background threads gated by a quit
event, and the dialogs are drawn with tkinter.

::: lmstudio_tray.WindowsTrayIcon
    options:
      show_root_heading: true
      show_source: true
      members: true
      group_by_category: true

### Dialog helpers

::: lmstudio_tray
    options:
      members:
        - _run_tk_dialog
        - _show_tk_message
        - _prompt_tk_endpoint

### Autostart

Windows has no per-app login-item setting of its own, so the tray offers one
under **Options → Start with Windows**. It writes the same Startup-folder
shortcut as `lmstudio_autostart.ps1 -InstallAutostart` and the installer's
autostart task, which is what lets the menu's checkbox report the true state
however autostart was switched on.

::: lmstudio_tray
    options:
      members:
        - is_autostart_enabled
        - enable_autostart
        - disable_autostart
        - get_autostart_shortcut_path
