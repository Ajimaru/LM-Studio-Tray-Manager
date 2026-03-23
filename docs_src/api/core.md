# Core Functions

Utility functions for system operations, logging, and file management.

## Logging

::: lmstudio_tray.HomeMaskFormatter
    options:
      show_root_heading: true
      show_source: true

## File and Path Management

::: lmstudio_tray
    options:
      members:
        - _get_default_script_dir
        - _get_writable_logs_dir
        - get_asset_path

## Clipboard and URL Handling

::: lmstudio_tray
    options:
      members:
        - _copy_to_clipboard
        - _activate_link
        - _validate_url_scheme
        - _is_allowed_update_url
        - get_release_url

## Application State

::: lmstudio_tray._AppState
    options:
      show_root_heading: true
      show_source: true
      members: true

::: lmstudio_tray
    options:
      members:
        - sync_app_state_for_tests
