import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen import gif as gif_mod

try:
    from PIL import Image

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

pytestmark = pytest.mark.skipif(not _HAS_PIL, reason="Pillow not installed")


def _make_gif_bytes(width: int, height: int, frames: int = 5, durations=None) -> bytes:
    imgs = []
    for i in range(frames):
        img = Image.new("RGB", (width, height), color=(10 * i, 20, 30))
        imgs.append(img.convert("P", palette=Image.ADAPTIVE))
    buf = io.BytesIO()
    imgs[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=imgs[1:],
        duration=durations if durations is not None else 60,
        loop=0,
    )
    return buf.getvalue()


def test_square_crop_gif_crops_non_square_to_square():
    """Regression test for the actual observed bug: a native Wan2.2 ComfyUI GIF came back
    448x640 (portrait) from a 1024x1024 square source PNG, and was written as-is -- looking
    stretched wherever displayed as a circular/square avatar.
    """
    data = _make_gif_bytes(448, 640, frames=6)
    cropped, frame_count, side = gif_mod.square_crop_gif(data)

    assert frame_count == 6
    assert side == 448  # min(448, 640)

    out = Image.open(io.BytesIO(cropped))
    assert out.size == (448, 448)
    assert out.n_frames == 6


def test_square_crop_gif_leaves_already_square_gif_unchanged_in_size():
    data = _make_gif_bytes(300, 300, frames=4)
    cropped, frame_count, side = gif_mod.square_crop_gif(data)

    assert frame_count == 4
    assert side == 300
    out = Image.open(io.BytesIO(cropped))
    assert out.size == (300, 300)


def test_square_crop_gif_preserves_loop_and_per_frame_duration():
    durations = [50, 60, 70, 80]
    data = _make_gif_bytes(200, 400, frames=4, durations=durations)
    cropped, _frame_count, _side = gif_mod.square_crop_gif(data)

    out = Image.open(io.BytesIO(cropped))
    assert out.info.get("loop") == 0
    seen_durations = []
    for i in range(out.n_frames):
        out.seek(i)
        seen_durations.append(out.info.get("duration"))
    assert seen_durations == durations


def test_synthesize_gif_output_is_square_when_source_is_square():
    # A flat, textureless source produces pixel-identical frames after the zoom/crop pipeline
    # (nothing in a solid color changes when you zoom into it), which some GIF encoders collapse
    # to a single frame -- use a textured fixture so frames are genuinely distinguishable.
    src = Image.new("RGB", (256, 256), color=(50, 60, 70))
    for x in range(0, 256, 16):
        for y in range(0, 256, 16):
            src.putpixel((x, y), (255, 255, 255))
    png_buf = io.BytesIO()
    src.save(png_buf, format="PNG")

    result = gif_mod.synthesize_gif(png_buf.getvalue(), frames=6, duration_ms=80)
    out = Image.open(io.BytesIO(result))
    assert out.size == (256, 256)
    # the ping-pong phase formula puts frame 0 and the last frame at the same (zero) phase by
    # design (a seamless loop boundary), so they can collapse to one frame in the encoded GIF --
    # assert a multi-frame animation without pinning the exact count to that implementation detail.
    assert out.n_frames >= 5
