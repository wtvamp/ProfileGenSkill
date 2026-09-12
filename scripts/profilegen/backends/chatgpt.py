"""ChatGPT (OpenAI Images API) backend."""
from __future__ import annotations

import base64
from typing import Any

from .. import http
from .base import BackendError, ImageResult, NotSupported, PromptSpec

DEFAULT_BASE_URL = "https://api.openai.com"
DEFAULT_MODEL = "gpt-image-1"


class ChatGPTBackend:
    name = "chatgpt"
    supports_native_gif = False

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg

    def validate(self, cfg: dict[str, Any]) -> list[str]:
        errors = []
        if not cfg.get("openai_api_key"):
            errors.append("openai_api_key is not set (env OPENAI_API_KEY)")
        return errors

    def generate_image(self, spec: PromptSpec) -> ImageResult:
        cfg = self.cfg
        api_key = cfg.get("openai_api_key")
        if not api_key:
            raise BackendError("openai_api_key is not set (env OPENAI_API_KEY)")
        base_url = (cfg.get("openai_base_url") or DEFAULT_BASE_URL).rstrip("/")
        model = cfg.get("openai_image_model") or DEFAULT_MODEL

        body: dict[str, Any] = {
            "model": model,
            "prompt": spec.positive,
            "n": 1,
            "size": f"{spec.width}x{spec.height}",
        }
        if spec.nsfw:
            body["moderation"] = "low"

        headers = {"Authorization": f"Bearer {api_key}"}
        resp = http.json_post(f"{base_url}/v1/images/generations", headers, body)

        try:
            b64 = resp["data"][0]["b64_json"]
        except (KeyError, IndexError, TypeError) as e:
            raise BackendError(f"Unexpected ChatGPT response shape: {resp}") from e

        try:
            data = base64.b64decode(b64)
        except Exception as e:
            raise BackendError(f"Could not decode base64 image data from ChatGPT: {e}") from e

        return ImageResult(
            data=data,
            format="png",
            backend=self.name,
            model=model,
            seed=spec.seed,
            width=spec.width,
            height=spec.height,
            raw_meta={"response": {k: v for k, v in resp.items() if k != "data"}},
        )

    def generate_gif(self, spec: PromptSpec) -> ImageResult:
        raise NotSupported("ChatGPT backend does not support native GIF generation")
