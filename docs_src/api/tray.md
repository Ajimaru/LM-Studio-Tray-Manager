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
