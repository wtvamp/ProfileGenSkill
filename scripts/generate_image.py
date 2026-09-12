#!/usr/bin/env python3
"""CLI: build a PromptSpec from raw prompt-file text and generate an image via the chosen backend.

The subject/style description is read verbatim from --prompt-file, then run through
profilegen.prompt.build() -- which appends the backend-appropriate NSFW clause when --nsfw is
set (a suggestive/artistic clause for hosted backends with a vendor classifier -- chatgpt/grok/
grok-cli -- vs. a direct/explicit clause for comfyui, which has none) and fills in the default
negative prompt. Callers (SKILL.md) should NOT hand-append an NSFW clause themselves -- this is
code-enforced specifically so the right phrasing is used regardless of what gets typed into the
prompt file, per profilegen/prompt.py's module docstring.

This is explicitly a profile-*picture* generator -- the output is meant to work as a circular/
square avatar -- so when Pillow is available the saved image is always center-cropped to
square, regardless of what the backend returned or claimed. This matters because not every
backend actually controls its own output size: Grok's API in particular ignores width/height
entirely and can return any aspect ratio, and a non-square image rendered into a square/circular
avatar frame without preserving aspect ratio is what "stretched profile picture" bugs look like
in practice. `width`/`height` in the printed JSON are always the image's real, final (already
square, when Pillow is available) dimensions -- never a backend's requested-but-unverified size.

Prints one JSON object to stdout: {"path", "backend", "model", "seed", "width", "height",
"positive_prompt", "negative_prompt"} on success, or {"error": "..."} with a nonzero exit code
on failure.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import config, prompt  # noqa: E402
from profilegen.backends import get_backend  # noqa: E402
from profilegen.backends.base import BackendError, PromptSpec  # noqa: E402
from profilegen.config import ConfigError  # noqa: E402

try:
    from PIL import Image
    import io

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


def _read_text(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).read_text(encoding="utf-8").strip()


def _save_squared(data: bytes, out_path: Path) -> tuple[str, int, int]:
    """Decode ``data``, center-crop to square if it isn't already, and save to ``out_path``
    (as PNG if its suffix says so, else in the decoded image's own format). Returns
    (actual_path, width, height) of what was actually written -- always square.
    """
    img = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = img.size
    if w != h:
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    save_format = "PNG" if out_path.suffix.lower() == ".png" else "JPEG"
    if save_format == "JPEG" and out_path.suffix.lower() not in (".jpg", ".jpeg"):
        out_path = out_path.with_suffix(".jpg")
    img.save(out_path, format=save_format)
    return str(out_path), img.width, img.height


def _save_raw(data: bytes, fmt: str, out_path: Path) -> str:
    """Fallback with no Pillow available: write the backend's bytes as-is (no cropping/
    conversion possible), at the correct extension for its actual format.
    """
    if out_path.suffix.lower().lstrip(".") != fmt:
        out_path = out_path.with_suffix(f".{fmt}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return str(out_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a profile image via a backend")
    parser.add_argument("--backend", required=True, choices=["chatgpt", "grok", "grok-cli", "comfyui", "mock"])
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--negative-file")
    parser.add_argument("--nsfw", action="store_true")
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--workflow", help="override comfyui_workflow path (e.g. a freshly authored one)")
    parser.add_argument("--style-preset", help="optional short style clause, e.g. 'anime style'")
    args = parser.parse_args()

    try:
        raw_positive = _read_text(args.prompt_file)
        raw_negative = _read_text(args.negative_file)

        cfg = config.resolve(args.backend, {"comfyui_workflow": args.workflow})
        backend_cls = get_backend(args.backend)
        backend = backend_cls(cfg)

        positive, negative = prompt.build(
            raw_positive,
            raw_negative,
            nsfw=args.nsfw,
            style_preset=args.style_preset,
            backend=args.backend,
        )

        spec = PromptSpec(
            positive=positive,
            negative=negative,
            nsfw=args.nsfw,
            seed=args.seed,
            width=args.width,
            height=args.height,
        )

        result = backend.generate_image(spec)

        out_path = Path(args.out)
        if _HAS_PIL:
            actual_path, final_width, final_height = _save_squared(result.data, out_path)
        else:
            actual_path = _save_raw(result.data, result.format, out_path)
            # Without Pillow we cannot decode the real dimensions or crop to square; only trust
            # the backend's reported size when the backend actually controls it (Grok reports
            # None/None for exactly this reason -- see backends/grok.py).
            final_width, final_height = result.width, result.height

        print(
            json.dumps(
                {
                    "path": actual_path,
                    "backend": result.backend,
                    "model": result.model,
                    "seed": result.seed,
                    "width": final_width,
                    "height": final_height,
                    "positive_prompt": positive,
                    "negative_prompt": negative,
                }
            )
        )
        return 0
    except (BackendError, ConfigError) as e:
        print(json.dumps({"error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
