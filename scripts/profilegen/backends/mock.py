"""Mock backend: no network, draws a placeholder PNG. Used for offline pipeline testing,
including verifying the NSFW-flag plumbing (an NSFW image gets a visible badge).
"""
from __future__ import annotations

import random
import struct
import zlib
from typing import Any

from .base import ImageResult, NotSupported, PromptSpec

try:
    from PIL import Image, ImageDraw

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


def _render_with_pillow(spec: PromptSpec) -> bytes:
    import io

    img = Image.new("RGB", (spec.width, spec.height), color=(40, 40, 60))
    draw = ImageDraw.Draw(img)
    text = spec.positive[:40]
    draw.text((16, 16), text, fill=(255, 255, 255))
    draw.text((16, 40), f"backend=mock seed={spec.seed}", fill=(180, 180, 200))
    if spec.nsfw:
        draw.rectangle([spec.width - 110, 10, spec.width - 10, 50], fill=(200, 0, 0))
        draw.text((spec.width - 100, 20), "NSFW", fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _render_raw_png(spec: PromptSpec) -> bytes:
    """Minimal valid PNG built by hand (no Pillow available): a solid-colored image,
    optionally with a red badge block in the corner when nsfw is set, so the NSFW
    plumbing is still visible/verifiable without any imaging library.
    """
    width, height = spec.width, spec.height
    bg = (40, 40, 60)
    badge = (200, 0, 0)
    badge_w = min(100, width)
    badge_h = min(40, height)

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type: none
        in_badge_row = spec.nsfw and y < badge_h
        for x in range(width):
            if in_badge_row and x >= width - badge_w:
                raw.extend(badge)
            else:
                raw.extend(bg)

    compressed = zlib.compress(bytes(raw), level=6)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        sig
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", compressed)
        + _png_chunk(b"IEND", b"")
    )
    return png


class MockBackend:
    name = "mock"
    supports_native_gif = False

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg

    def validate(self, cfg: dict[str, Any]) -> list[str]:
        return []

    def generate_image(self, spec: PromptSpec) -> ImageResult:
        seed = spec.seed if spec.seed is not None else random.getrandbits(32)
        spec = PromptSpec(
            positive=spec.positive,
            negative=spec.negative,
            nsfw=spec.nsfw,
            seed=seed,
            width=spec.width,
            height=spec.height,
        )
        if _HAS_PIL:
            data = _render_with_pillow(spec)
        else:
            data = _render_raw_png(spec)

        return ImageResult(
            data=data,
            format="png",
            backend=self.name,
            model="mock-v1",
            seed=seed,
            width=spec.width,
            height=spec.height,
            raw_meta={"pillow": _HAS_PIL},
        )

    def generate_gif(self, spec: PromptSpec) -> ImageResult:
        raise NotSupported("Mock backend does not support native GIF generation")
