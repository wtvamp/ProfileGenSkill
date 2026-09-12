"""Backend registry."""
from __future__ import annotations

from typing import Any

from .chatgpt import ChatGPTBackend
from .comfyui import ComfyUIBackend
from .grok import GrokBackend
from .grok_cli import GrokCliBackend
from .mock import MockBackend

REGISTRY = {
    "chatgpt": ChatGPTBackend,
    "grok": GrokBackend,
    "grok-cli": GrokCliBackend,
    "comfyui": ComfyUIBackend,
    "mock": MockBackend,
}


class UnknownBackendError(KeyError):
    pass


def get_backend(name: str):
    try:
        return REGISTRY[name]
    except KeyError:
        valid = ", ".join(sorted(REGISTRY))
        raise UnknownBackendError(
            f"Unknown backend {name!r}. Valid backends: {valid}"
        ) from None
