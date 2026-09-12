"""GIF assembly and normalization. Pure image processing, no network calls. Requires Pillow.
Dispatch between the synthetic path (below) and a backend's native animation workflow (ComfyUI/
grok-cli) happens in scripts/make_gif.py, not here.

Also owns ``square_crop_gif`` -- native (generative) GIF backends commonly return whatever
aspect ratio the underlying video model defaults to, not the square shape a profile picture
needs. Observed in practice: a Wan2.2 image-to-video ComfyUI workflow returned a 448x640
(portrait) GIF from a 1024x1024 square source PNG, which then looked stretched wherever it was
displayed as a circular/square avatar. ``scripts/make_gif.py`` runs every native-mode result
through this before writing it, mirroring what ``scripts/generate_image.py`` already does for
still images.
"""
from __future__ import annotations

import io
import math

try:
    from PIL import Image

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


def synthesize_gif(png_bytes: bytes, frames: int = 24, duration_ms: int = 80) -> bytes:
    """Produce a looping GIF: a slow zoom (1.00 -> 1.06 -> 1.00) plus a slight horizontal
    drift, from a single source image. Deterministic and free of any generation cost.
    """
    if not _HAS_PIL:
        raise RuntimeError("Pillow is required for GIF synthesis: pip install Pillow")

    base = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    width, height = base.size
    max_zoom = 0.06
    max_drift = max(2, width // 200)

    gif_frames = []
    for i in range(frames):
        # Ping-pong 0 -> 1 -> 0 across the sequence via a sine wave.
        phase = math.sin(math.pi * i / max(1, frames - 1))
        zoom = 1.0 + max_zoom * phase
        drift = int(max_drift * phase)

        scaled_w = max(1, round(width * zoom))
        scaled_h = max(1, round(height * zoom))
        scaled = base.resize((scaled_w, scaled_h), Image.LANCZOS)

        left = (scaled_w - width) // 2 + drift
        top = (scaled_h - height) // 2
        left = max(0, min(left, scaled_w - width))
        top = max(0, min(top, scaled_h - height))

        cropped = scaled.crop((left, top, left + width, top + height))
        gif_frames.append(cropped.convert("P", palette=Image.ADAPTIVE))

    buf = io.BytesIO()
    gif_frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=gif_frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )
    return buf.getvalue()


def square_crop_gif(data: bytes) -> tuple[bytes, int, int]:
    """Center-crop every frame of an animated GIF to square, preserving per-frame duration and
    loop count. Returns (cropped_gif_bytes, frame_count, side_length).

    Use this on any native (generative) GIF/video-backend result before writing it -- a video
    model choosing its own default resolution independent of the source still image's aspect
    ratio is a normal, observed occurrence, not an edge case.
    """
    if not _HAS_PIL:
        raise RuntimeError("Pillow is required for GIF square-cropping: pip install Pillow")

    src = Image.open(io.BytesIO(data))
    n_frames = getattr(src, "n_frames", 1)
    loop = src.info.get("loop", 0)

    cropped_frames = []
    durations = []
    for i in range(n_frames):
        src.seek(i)
        frame = src.convert("RGB")
        w, h = frame.size
        if w != h:
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            frame = frame.crop((left, top, left + side, top + side))
        cropped_frames.append(frame.convert("P", palette=Image.ADAPTIVE))
        durations.append(src.info.get("duration", 80))

    buf = io.BytesIO()
    cropped_frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=cropped_frames[1:],
        duration=durations,
        loop=loop,
        optimize=False,
    )
    return buf.getvalue(), n_frames, cropped_frames[0].size[0]
