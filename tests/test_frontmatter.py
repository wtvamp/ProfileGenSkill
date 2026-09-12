import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen import frontmatter, render  # noqa: E402

FIELDS = {
    "name": "Ada Sterling",
    "slug": "ada-sterling",
    "image": "profiles/ada-sterling/ada-sterling.png",
    "voice": "af_jessica",
    "personality": "Warm, precise, and a little wry.",
    "nsfw": False,
    "display": {"image": True, "name": False},
    "generation": {
        "backend": "mock",
        "model": "mock-v1",
        "prompt": "portrait of a person",
        "negative_prompt": "blurry",
        "seed": 42,
        "gif_mode": None,
        "created_at": "2026-09-10T00:00:00Z",
    },
}


def test_extract_frontmatter_roundtrips_render_standalone():
    rendered = render.render_standalone(FIELDS)
    parsed = frontmatter.extract_frontmatter(rendered)
    assert parsed["name"] == "Ada Sterling"
    assert parsed["slug"] == "ada-sterling"
    assert parsed["image"] == FIELDS["image"]
    assert parsed["nsfw"] is False
    assert parsed["display"]["image"] is True
    assert parsed["display"]["name"] is False
    assert parsed["generation"]["backend"] == "mock"
    assert parsed["generation"]["seed"] == 42
    assert parsed["generation"]["gif_mode"] is None


def test_extract_frontmatter_none_without_leading_dashes():
    assert frontmatter.extract_frontmatter("# just a heading\nno frontmatter here\n") is None


def test_extract_frontmatter_none_with_unterminated_block():
    assert frontmatter.extract_frontmatter("---\nname: X\n") is None


def test_find_marker_slugs_and_ref_import():
    text = (
        "some project notes\n\n"
        "<!-- profile-gen:start slug=ada-sterling -->\n"
        "@profiles/ada-sterling/ada-sterling.md\n"
        "<!-- profile-gen:end slug=ada-sterling -->\n"
    )
    assert frontmatter.find_marker_slugs(text) == ["ada-sterling"]
    assert (
        frontmatter.extract_ref_import(text, "ada-sterling")
        == "profiles/ada-sterling/ada-sterling.md"
    )


def test_find_marker_slugs_multiple_in_order():
    text = (
        "<!-- profile-gen:start slug=first -->\n@a.md\n<!-- profile-gen:end slug=first -->\n"
        "<!-- profile-gen:start slug=second -->\n@b.md\n<!-- profile-gen:end slug=second -->\n"
    )
    assert frontmatter.find_marker_slugs(text) == ["first", "second"]


def test_extract_ref_import_missing_slug_returns_none():
    text = "<!-- profile-gen:start slug=ada -->\n@ada.md\n<!-- profile-gen:end slug=ada -->\n"
    assert frontmatter.extract_ref_import(text, "someone-else") is None


def test_extract_embedded_block_roundtrips_render_embedded():
    rendered = render.render_embedded(FIELDS)
    parsed = frontmatter.extract_embedded_block(rendered, "ada-sterling")
    assert parsed["name"] == "Ada Sterling"
    assert parsed["image"] == FIELDS["image"]
    assert parsed["display"]["image"] is True
    assert parsed["display"]["name"] is False


def test_extract_embedded_block_missing_slug_returns_none():
    rendered = render.render_embedded(FIELDS)
    assert frontmatter.extract_embedded_block(rendered, "no-such-slug") is None
