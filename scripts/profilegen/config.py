"""Config resolution: CLI flag > env var > ./.claude/profile-gen.json > ~/.claude/profile-gen.json."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# key -> env var name
_KEYS = {
    "openai_api_key": "OPENAI_API_KEY",
    "xai_api_key": "XAI_API_KEY",
    "comfyui_url": "COMFYUI_URL",
    "comfyui_workflow": "COMFYUI_WORKFLOW",
    "comfyui_gif_workflow": "COMFYUI_GIF_WORKFLOW",
    "comfyui_timeout_s": "COMFYUI_TIMEOUT_S",
    "comfyui_client_id": "COMFYUI_CLIENT_ID",
    "openai_base_url": "OPENAI_BASE_URL",
    "openai_image_model": "OPENAI_IMAGE_MODEL",
    "xai_image_model": "XAI_IMAGE_MODEL",
    "grok_cli_bin": "GROK_CLI_BIN",
    "grok_cli_workdir": "GROK_CLI_WORKDIR",
    "grok_cli_timeout_s": "GROK_CLI_TIMEOUT_S",
    "default_backend": "PROFILEGEN_DEFAULT_BACKEND",
    "default_voice": "PROFILEGEN_DEFAULT_VOICE",
    "style_preset": "PROFILEGEN_STYLE_PRESET",
}

_INT_KEYS = {"comfyui_timeout_s", "grok_cli_timeout_s"}


class ConfigError(Exception):
    """Raised when a config file is malformed or otherwise unusable."""


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"Could not read config file {path}: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(f"Malformed JSON in config file {path}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"Config file {path} must contain a JSON object")
    return data


def _coerce(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in _INT_KEYS:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    return value


def resolve(backend: str, cli_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge config with precedence: cli_overrides > env vars > ./.claude/profile-gen.json
    > ~/.claude/profile-gen.json. Returns a dict with all known keys (missing ones as None),
    plus a ``backend`` key set to the requested backend name.
    """
    cli_overrides = cli_overrides or {}

    home_cfg = _load_json_file(Path.home() / ".claude" / "profile-gen.json")
    local_cfg = _load_json_file(Path.cwd() / ".claude" / "profile-gen.json")

    result: dict[str, Any] = {"backend": backend}
    for key in _KEYS:
        value = None
        if key in home_cfg:
            value = home_cfg[key]
        if key in local_cfg:
            value = local_cfg[key]
        env_name = _KEYS[key]
        if env_name in os.environ:
            value = os.environ[env_name]
        if key in cli_overrides and cli_overrides[key] is not None:
            value = cli_overrides[key]
        result[key] = _coerce(key, value)

    # pass through any extra CLI overrides not in the known key set (e.g. one-off flags)
    for key, value in cli_overrides.items():
        if key not in result and value is not None:
            result[key] = value

    return result
