# Configuration Management

Functions for loading, validating, and managing application configuration.

## Configuration File

The application stores configuration at `~/.config/lmstudio_tray.json`.

## Configuration Functions

::: lmstudio_tray
    options:
      members:
        - _get_config_path
        - load_config
        - save_config
        - _normalize_api_port

## Autostart (macOS)

Login startup is a per-user LaunchAgent at
`~/Library/LaunchAgents/com.lmstudio.tray-manager.plist`. `KeepAlive` is
deliberately off so that quitting the tray keeps it closed.

::: lmstudio_tray
    options:
      members:
        - get_launch_agent_path
        - get_launch_target
        - is_autostart_enabled
        - autostart_includes_daemon
        - enable_autostart
        - disable_autostart

## API Configuration

`is_remote_endpoint` decides whether status comes from local process
detection or from the HTTP API; a host's own addresses count as local.

Load state is read from LM Studio's native `/api/v0/models`, which reports a
`state` field per model. The OpenAI-compatible `/v1/models` lists available
models without saying which are loaded, so it is only a reachability
fallback for builds that do not serve `/api/v0`.

::: lmstudio_tray
    options:
      members:
        - get_api_base_url
        - get_api_models_url
        - get_native_api_models_url
        - parse_host_port
        - is_remote_endpoint
        - check_api_reachable
        - get_api_loaded_models

## LM Studio Commands

`is_daemon_available` is the availability test to use: LM Studio embeds
llmster and starts it via `lms daemon up`, so `get_llmster_cmd` alone
reports "missing" on machines where the daemon actually runs.

::: lmstudio_tray
    options:
      members:
        - get_lms_cmd
        - get_llmster_cmd
        - is_daemon_available
        - _has_loaded_model
