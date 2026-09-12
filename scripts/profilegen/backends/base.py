"""Shared contract for image-generation backends (ChatGPT, Grok, ComfyUI, mock).

All backends implement the ``ImageBackend`` protocol. A backend takes a
``PromptSpec`` and returns an ``ImageResult``. The NSFW flag on ``PromptSpec``
is a pure pass-through: backends must forward it to the underlying provider
(or, for ComfyUI, use it to select which negative-prompt terms to include)
without adding any additional client-side filtering.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


class NotSupported(Exception):
    """Raised when a backend is asked to do something it cannot do (e.g. native GIF)."""


class BackendError(Exception):
    """Raised on any backend/provider failure. The message is surfaced verbatim to the user."""


@dataclass
class PromptSpec:
    positive: str
    negative: Optional[str] = None
    nsfw: bool = False
    seed: Optional[int] = None
    width: int = 1024
    height: int = 1024


@dataclass
class ImageResult:
    data: bytes
    format: str  # "png" | "jpeg" | "gif"
    backend: str
    model: str
    seed: Optional[int]
    width: Optional[int]
    height: Optional[int]
    raw_meta: dict = field(default_factory=dict)


class ImageBackend(Protocol):
    name: str
    supports_native_gif: bool

    def validate(self, cfg: dict[str, Any]) -> list[str]:
        """Return a list of human-readable config error strings (empty = OK)."""
        ...

    def generate_image(self, spec: PromptSpec) -> ImageResult:
        ...

    def generate_gif(self, spec: PromptSpec) -> ImageResult:
        """Raise NotSupported if supports_native_gif is False."""
        ...
