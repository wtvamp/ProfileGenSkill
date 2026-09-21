import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen import variants  # noqa: E402


def _persona(**overrides):
    fields = {
        "name": "Test Persona",
        "image": "profiles/test/test.png",
        "display": {"image": True, "name": True, "autostart": True, "variant": "sfw"},
    }
    fields.update(overrides)
    return fields


def test_sfw_only_persona_has_one_variant():
    fields = _persona()
    assert variants.paths(fields) == {"sfw": "profiles/test/test.png"}
    assert variants.has(fields, "sfw")
    assert not variants.has(fields, "nsfw")


def test_both_variants_resolve_to_their_own_picture():
    fields = _persona(image_nsfw="profiles/test/test-nsfw.png", nsfw=True)

    sfw = variants.resolve(fields)
    assert (sfw.variant, sfw.path, sfw.fell_back) == ("sfw", "profiles/test/test.png", False)

    nsfw = variants.resolve(fields, "nsfw")
    assert (nsfw.variant, nsfw.path, nsfw.fell_back) == ("nsfw", "profiles/test/test-nsfw.png", False)


def test_stored_variant_is_used_when_no_override_is_given():
    fields = _persona(image_nsfw="profiles/test/test-nsfw.png", nsfw=True)
    fields["display"]["variant"] = "nsfw"
    assert variants.stored_variant(fields) == "nsfw"
    assert variants.resolve(fields).path == "profiles/test/test-nsfw.png"


def test_asking_for_a_missing_variant_falls_back_and_says_so():
    fields = _persona()
    resolution = variants.resolve(fields, "nsfw")
    assert resolution.requested == "nsfw"
    assert resolution.variant == "sfw"
    assert resolution.path == "profiles/test/test.png"
    assert resolution.fell_back is True


def test_persona_with_no_picture_at_all_resolves_to_nothing():
    resolution = variants.resolve({"name": "Nameless"})
    assert resolution.variant is None
    assert resolution.path is None
    assert resolution.fell_back is False


def test_legacy_nsfw_persona_keeps_its_single_picture_as_the_nsfw_one():
    """A profile written before variants existed: nsfw: true with one `image` and no
    `image_nsfw`. Its picture is the explicit one, so it must not be offered as the SFW
    variant."""
    legacy = {"name": "Legacy", "image": "profiles/legacy/legacy.png", "nsfw": True}

    assert variants.paths(legacy) == {"nsfw": "profiles/legacy/legacy.png"}
    assert not variants.has(legacy, "sfw")

    # it still displays -- the stored default of sfw falls back to the one picture it has
    resolution = variants.resolve(legacy)
    assert resolution.variant == "nsfw"
    assert resolution.fell_back is True


def test_legacy_sfw_persona_is_unchanged():
    legacy = {"name": "Legacy", "image": "profiles/legacy/legacy.png", "nsfw": False}
    assert variants.paths(legacy) == {"sfw": "profiles/legacy/legacy.png"}
    assert variants.resolve(legacy).path == "profiles/legacy/legacy.png"


def test_stored_variant_defaults_to_sfw_for_junk_or_missing_values():
    assert variants.stored_variant({}) == "sfw"
    assert variants.stored_variant({"display": {"variant": "banana"}}) == "sfw"
    assert variants.stored_variant({"display": {"variant": "NSFW"}}) == "nsfw"


def test_other_flips_the_variant():
    assert variants.other("sfw") == "nsfw"
    assert variants.other("nsfw") == "sfw"


def test_missing_reason_explains_the_legacy_shape_rather_than_claiming_image_is_unset():
    legacy = {"name": "Legacy", "image": "profiles/legacy/legacy.png", "nsfw": True}
    reason = variants.missing_reason(legacy, "sfw")
    assert "predates variants" in reason
    assert "image is unset" not in reason


def test_missing_reason_for_a_plain_sfw_persona_points_at_image_nsfw():
    fields = _persona()
    assert "image_nsfw is unset" in variants.missing_reason(fields, "nsfw")
