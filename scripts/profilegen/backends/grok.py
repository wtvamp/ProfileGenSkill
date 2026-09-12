"""Grok (xAI Images API) backend.

Limitation: the xAI images endpoint does not accept size or negative-prompt parameters --
``spec.width``/``spec.height``/``spec.negative`` are ignored on the wire, and Grok is free to
return whatever aspect ratio it wants (commonly non-square). ``ImageResult.width``/``height``
are reported as ``None`` here rather than echoing back ``spec.width``/``spec.height`` -- doing
that previously was actively wrong (it claimed a square image whether or not one was actually
returned) and caused a real, observed bug: a non-square Grok output rendered as a stretched
profile picture wherever it was displayed as a circular/square avatar without preserving aspect
ratio. Callers that need the real dimensions must decode the returned bytes themselves (which
scripts/generate_image.py now does, since it's also where the square-crop normalization for
profile pictures lives). Grok returns JPEG, not PNG.
"""
from __future__ import annotations

import base64
from typing import Any

from .. import http
from .base import BackendError, ImageResult, NotSupported, PromptSpec

API_URL = "https://api.x.ai/v1/images/generations"
DEFAULT_MODEL = "grok-2-image"


class GrokBackend:
    name = "grok"
    supports_native_gif = False

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg

    def validate(self, cfg: dict[str, Any]) -> list[str]:
        errors = []
        if not cfg.get("xai_api_key"):
            errors.append("xai_api_key is not set (env XAI_API_KEY)")
        return errors

    def generate_image(self, spec: PromptSpec) -> ImageResult:
        cfg = self.cfg
        api_key = cfg.get("xai_api_key")
        if not api_key:
            raise BackendError("xai_api_key is not set (env XAI_API_KEY)")
        model = cfg.get("xai_image_model") or DEFAULT_MODEL

        body = {
            "model": model,
            "prompt": spec.positive,
            "n": 1,
            "response_format": "b64_json",
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = http.json_post(API_URL, headers, body)

        try:
            b64 = resp["data"][0]["b64_json"]
        except (KeyError, IndexError, TypeError) as e:
            raise BackendError(f"Unexpected Grok response shape: {resp}") from e

        try:
            data = base64.b64decode(b64)
        except Exception as e:
            raise BackendError(f"Could not decode base64 image data from Grok: {e}") from e

        return ImageResult(
            data=data,
            format="jpeg",
            backend=self.name,
            model=model,
            seed=spec.seed,
            width=None,
            height=None,
            raw_meta={"response": {k: v for k, v in resp.items() if k != "data"}},
        )

    def generate_gif(self, spec: PromptSpec) -> ImageResult:
        raise NotSupported("Grok backend does not support native GIF generation")
