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

::: lmstudio_tray
    options:
      members:
        - get_lms_cmd
        - get_llmster_cmd
        - _has_loaded_model
