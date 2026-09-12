import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    from PIL import Image

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


def _run(args, cwd):
    return subprocess.run([sys.executable, *args], capture_output=True, text=True, cwd=str(cwd))


@pytest.mark.skipif(not _HAS_PIL, reason="Pillow not installed")
def test_non_square_output_is_center_cropped_to_square(tmp_path):
    """This is the actual bug being regression-tested: a backend (like Grok, in practice) can
    return a non-square image. A profile picture must always end up square regardless -- a
    non-square image is what "stretched" avatars downstream turn out to be.
    """
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("a landscape-oriented test persona", encoding="utf-8")
    out_path = tmp_path / "persona.png"

    result = _run(
        [
            "scripts/generate_image.py",
            "--backend",
            "mock",
            "--prompt-file",
            str(prompt_file),
            "--out",
            str(out_path),
            "--width",
            "1200",
            "--height",
            "800",
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)

    assert report["width"] == report["height"] == 800
    with Image.open(report["path"]) as img:
        assert img.size == (800, 800)


@pytest.mark.skipif(not _HAS_PIL, reason="Pillow not installed")
def test_already_square_output_is_unchanged_in_size(tmp_path):
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("a square test persona", encoding="utf-8")
    out_path = tmp_path / "persona.png"

    result = _run(
        [
            "scripts/generate_image.py",
            "--backend",
            "mock",
            "--prompt-file",
            str(prompt_file),
            "--out",
            str(out_path),
            "--width",
            "512",
            "--height",
            "512",
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["width"] == report["height"] == 512
