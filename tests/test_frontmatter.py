import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen import frontmatter, render  # noqa: E402

FIELDS = {
    "name": "Ada Sterling",
    "slug": "ada-sterling",
    "image": "profiles/ada-sterling/ada-sterling.png",
    "voice": "af_jessica",
    "personality": "Warm, precise, and a little wry.",
    "nsfw": False,
    "display": {"image": True, "name": False, "autostart": True},
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


def test_block_span_covers_markers_and_missing_slug_is_none():
    text = (
        "<!-- profile-gen:start slug=ada -->\ncontent here\n<!-- profile-gen:end slug=ada -->\n"
    )
    span = frontmatter.block_span(text, "ada")
    assert span is not None
    start, end = span
    assert text[start:end].startswith("<!-- profile-gen:start slug=ada -->")
    assert text[start:end].endswith("<!-- profile-gen:end slug=ada -->")
    assert frontmatter.block_span(text, "someone-else") is None


def test_set_display_flags_whole_text_no_region():
    rendered = render.render_standalone(FIELDS)
    updated = frontmatter.set_display_flags(rendered, image=False)
    parsed = frontmatter.extract_frontmatter(updated)
    assert parsed["display"]["image"] is False
    assert parsed["display"]["name"] is False  # untouched from FIELDS' own False


def test_set_display_flags_both_fields():
    rendered = render.render_standalone(FIELDS)
    updated = frontmatter.set_display_flags(rendered, image=False, name=True)
    parsed = frontmatter.extract_frontmatter(updated)
    assert parsed["display"]["image"] is False
    assert parsed["display"]["name"] is True


def test_set_display_flags_none_none_is_noop():
    rendered = render.render_standalone(FIELDS)
    assert frontmatter.set_display_flags(rendered) == rendered


def test_set_display_flags_missing_block_raises():
    with pytest.raises(ValueError):
        frontmatter.set_display_flags("no display block here", image=True)


def test_set_display_flags_scoped_region_leaves_other_personas_alone():
    fields_a = dict(FIELDS, name="First", slug="first", display={"image": True, "name": True})
    fields_b = dict(FIELDS, name="Second", slug="second", display={"image": True, "name": True})
    text = render.render_embedded(fields_a) + "\n" + render.render_embedded(fields_b)

    span = frontmatter.block_span(text, "first")
    updated = frontmatter.set_display_flags(text, image=False, region=span)

    first = frontmatter.extract_embedded_block(updated, "first")
    second = frontmatter.extract_embedded_block(updated, "second")
    assert first["display"]["image"] is False
    assert second["display"]["image"] is True


def test_set_display_flags_appends_key_missing_from_an_older_profile():
    # a profile written before `autostart` existed has a two-key display block; setting the new
    # flag must add it rather than fail
    older = "---\nname: \"Ada\"\ndisplay:\n  image: true\n  name: true\ngeneration:\n  seed: 1\n---\n"
    updated = frontmatter.set_display_flags(older, autostart=False)
    parsed = frontmatter.extract_frontmatter(updated)
    assert parsed["display"] == {"image": True, "name": True, "autostart": False}
    assert parsed["generation"]["seed"] == 1  # nothing after the block disturbed


def test_set_display_flags_is_key_order_independent():
    scrambled = "---\ndisplay:\n  autostart: true\n  name: true\n  image: true\n---\n"
    updated = frontmatter.set_display_flags(scrambled, image=False, autostart=False)
    parsed = frontmatter.extract_frontmatter(updated)
    assert parsed["display"]["image"] is False
    assert parsed["display"]["autostart"] is False
    assert parsed["display"]["name"] is True


def test_set_display_flags_autostart_roundtrips():
    rendered = render.render_standalone(FIELDS)
    updated = frontmatter.set_display_flags(rendered, autostart=False)
    parsed = frontmatter.extract_frontmatter(updated)
    assert parsed["display"]["autostart"] is False
    assert parsed["display"]["image"] is True  # untouched
