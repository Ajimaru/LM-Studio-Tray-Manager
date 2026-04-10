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

::: lmstudio_tray
    options:
      members:
        - get_api_base_url
        - get_api_models_url

## LM Studio Commands

::: lmstudio_tray
    options:
      members:
        - get_lms_cmd
        - get_llmster_cmd
        - _has_loaded_model
