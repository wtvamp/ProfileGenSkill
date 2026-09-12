#!/usr/bin/env python3
"""CLI: turn a still profile image into an animated GIF, either via a backend's native
animation workflow (ComfyUI's AnimateDiff, or grok-cli's /imagine-video) or via synthetic
"living portrait" motion applied to the still image.

These are NOT equivalent in what actually moves:

- native: a generative model re-renders motion, so the *subject* can genuinely animate (blink,
  breathe, shift expression). To make sure it actually does that instead of just panning/zooming
  the camera over an otherwise static subject -- a common default failure mode for these
  pipelines -- this script appends profilegen.prompt.GIF_MOTION_CLAUSE to the native-mode prompt.
  It also center-crops the result to square when Pillow is available: video-generation backends
  (e.g. a Wan2.2 image-to-video ComfyUI workflow) commonly return whatever resolution the model
  defaults to, independent of the square source PNG's aspect ratio -- observed in practice as a
  1024x1024 still producing a 448x640 (portrait) GIF, which then looks stretched wherever it's
  displayed as a circular/square avatar.
- synthetic: a deterministic zoom+drift applied to a single still image via Pillow. There is no
  generative model in this path, so it is camera movement only -- the subject itself cannot move
  (blink, change expression, etc). Report this distinction to the user rather than implying
  synthetic GIFs show the person actually animating.

Prints one JSON object to stdout: {"path", "mode": "native"|"synthetic", "frames", "duration_ms"}
on success, or {"error": "..."} with a nonzero exit code on failure.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import config, gif, prompt  # noqa: E402
from profilegen.backends import get_backend  # noqa: E402
from profilegen.backends.base import BackendError, NotSupported, PromptSpec  # noqa: E402
from profilegen.config import ConfigError  # noqa: E402
from profilegen.prompt import add_gif_motion_clause  # noqa: E402


def _read_text(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).read_text(encoding="utf-8").strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an animated GIF for a profile image")
    parser.add_argument("--backend", required=True, choices=["chatgpt", "grok", "grok-cli", "comfyui", "mock"])
    parser.add_argument("--png", required=True, help="path to the already-generated still image")
    parser.add_argument("--out", required=True, help="output path for the GIF")
    parser.add_argument("--mode", choices=["auto", "native", "synthetic"], default="auto")
    parser.add_argument("--prompt-file", help="required for native mode")
    parser.add_argument("--negative-file")
    parser.add_argument("--nsfw", action="store_true")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--gif-workflow", help="override comfyui_gif_workflow path (e.g. a freshly authored one)")
    args = parser.parse_args()

    try:
        cfg = config.resolve(args.backend, {"comfyui_gif_workflow": args.gif_workflow})
        backend_cls = get_backend(args.backend)
        backend = backend_cls(cfg)

        mode = args.mode
        if mode == "auto":
            mode = "native" if getattr(backend, "supports_native_gif", False) else "synthetic"

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if mode == "native":
            if not getattr(backend, "supports_native_gif", False):
                print(json.dumps({"error": "native GIF requested but backend does not support it"}))
                return 1

            positive, negative = prompt.build(
                _read_text(args.prompt_file) or "",
                _read_text(args.negative_file),
                nsfw=args.nsfw,
                backend=args.backend,
            )
            spec = PromptSpec(
                positive=add_gif_motion_clause(positive),
                negative=negative,
                nsfw=args.nsfw,
                seed=args.seed,
            )
            result = backend.generate_gif(spec)

            if out_path.suffix.lower().lstrip(".") != result.format:
                out_path = out_path.with_suffix(f".{result.format}")

            data = result.data
            frame_count = None
            if result.format == "gif":
                try:
                    data, frame_count, _side = gif.square_crop_gif(data)
                except RuntimeError:
                    pass  # Pillow unavailable -- can't crop; ship the backend's raw output

            out_path.write_bytes(data)

            print(
                json.dumps(
                    {
                        "path": str(out_path),
                        "mode": "native",
                        "frames": frame_count,
                        "duration_ms": None,
                    }
                )
            )
            return 0

        # synthetic
        png_bytes = Path(args.png).read_bytes()
        frames = 24
        duration_ms = 80
        gif_bytes = gif.synthesize_gif(png_bytes, frames=frames, duration_ms=duration_ms)
        out_path.write_bytes(gif_bytes)

        print(
            json.dumps(
                {
                    "path": str(out_path),
                    "mode": "synthetic",
                    "frames": frames,
                    "duration_ms": duration_ms,
                }
            )
        )
        return 0
    except (BackendError, ConfigError, NotSupported, RuntimeError, OSError) as e:
        print(json.dumps({"error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
