import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen import render  # noqa: E402

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

FULL_FIELDS = {
    "name": "Ada Sterling",
    "slug": "ada-sterling",
    # the single image field pointing at an animated GIF -- gif_mode records how, there's no
    # separate animated-image field.
    "image": "profiles/ada-sterling/ada-sterling.gif",
    "voice": "af_jessica",
    "personality": "Warm, precise, and a little wry.",
    "nsfw": False,
    "generation": {
        "backend": "mock",
        "model": "mock-v1",
        "prompt": "portrait of a person",
        "negative_prompt": "blurry",
        "seed": 42,
        "gif_mode": "synthetic",
        "created_at": "2026-09-10T00:00:00Z",
    },
}

MINIMAL_FIELDS = {
    "name": "Rho",
    "slug": "rho",
    # the single image field pointing at a plain static PNG -- gif_mode null.
    "image": "profiles/rho/rho.png",
    "voice": None,
    "personality": None,
    "nsfw": False,
    "generation": {
        "backend": "mock",
        "model": "mock-v1",
        "prompt": "portrait",
        "negative_prompt": None,
        "seed": None,
        "gif_mode": None,
        "created_at": "2026-09-10T00:00:00Z",
    },
}


@pytest.mark.parametrize("fields", [FULL_FIELDS, MINIMAL_FIELDS])
def test_render_standalone_smoke(fields):
    out = render.render_standalone(fields)
    assert fields["name"] in out
    assert fields["image"] in out
    assert out.count("---") >= 2


@pytest.mark.parametrize("fields", [FULL_FIELDS, MINIMAL_FIELDS])
def test_render_embedded_smoke(fields):
    out = render.render_embedded(fields)
    assert f"<!-- profile-gen:start slug={fields['slug']} -->" in out
    assert f"<!-- profile-gen:end slug={fields['slug']} -->" in out
    assert "```yaml" in out
    assert "```" in out


def test_standalone_optional_fields_present_when_set():
    out = render.render_standalone(FULL_FIELDS)
    assert "voice:" in out
    assert "## Personality" in out
    assert FULL_FIELDS["personality"] in out


def test_standalone_optional_fields_absent_when_unset():
    out = render.render_standalone(MINIMAL_FIELDS)
    assert "voice:" not in out
    assert "## Personality" not in out


def test_embedded_optional_fields_present_when_set():
    out = render.render_embedded(FULL_FIELDS)
    assert "voice:" in out
    assert "**Personality:**" in out


def test_embedded_optional_fields_absent_when_unset():
    out = render.render_embedded(MINIMAL_FIELDS)
    assert "voice:" not in out
    assert "**Personality:**" not in out


def test_single_image_field_holds_gif_when_animated():
    out = render.render_standalone(FULL_FIELDS)
    assert "ada-sterling.gif" in out
    assert "image_animated" not in out


def test_single_image_field_holds_png_when_static():
    out = render.render_standalone(MINIMAL_FIELDS)
    assert "rho.png" in out
    assert "image_animated" not in out


@pytest.mark.skipif(yaml is None, reason="PyYAML not installed")
def test_standalone_frontmatter_is_valid_yaml():
    out = render.render_standalone(FULL_FIELDS)
    assert out.startswith("---\n")
    _, frontmatter, _ = out.split("---", 2)
    parsed = yaml.safe_load(frontmatter)
    assert parsed["name"] == "Ada Sterling"
    assert parsed["slug"] == "ada-sterling"
    assert parsed["nsfw"] is False
    assert parsed["generation"]["backend"] == "mock"
    assert parsed["generation"]["seed"] == 42


@pytest.mark.skipif(yaml is None, reason="PyYAML not installed")
def test_standalone_minimal_frontmatter_is_valid_yaml():
    out = render.render_standalone(MINIMAL_FIELDS)
    _, frontmatter, _ = out.split("---", 2)
    parsed = yaml.safe_load(frontmatter)
    assert parsed["name"] == "Rho"
    assert parsed["generation"]["seed"] is None
    assert parsed["generation"]["gif_mode"] is None


@pytest.mark.skipif(yaml is None, reason="PyYAML not installed")
def test_embedded_fenced_yaml_is_valid():
    out = render.render_embedded(FULL_FIELDS)
    fenced = out.split("```yaml", 1)[1].split("```", 1)[0]
    parsed = yaml.safe_load(fenced)
    assert parsed["slug"] == "ada-sterling"
    assert parsed["generation"]["model"] == "mock-v1"
