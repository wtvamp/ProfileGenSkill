import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen import prompt as prompt_mod


def test_nsfw_appends_clause_once_even_if_already_present():
    p1, _ = prompt_mod.build("a person", None, nsfw=True)
    assert prompt_mod.NSFW_CLAUSE in p1
    assert p1.count(prompt_mod._NSFW_MARKER) == 1

    # Calling build() again on the already-clause-bearing text should not double it.
    p2, _ = prompt_mod.build(p1, None, nsfw=True)
    assert p2.count(prompt_mod._NSFW_MARKER) == 1


def test_nsfw_strips_suppressing_terms_from_explicit_negative():
    _, neg = prompt_mod.build(
        "a person",
        "blurry, nsfw, nudity, watermark",
        nsfw=True,
    )
    lowered = neg.lower()
    for term in prompt_mod.DEFAULT_NEGATIVE_SUPPRESSING_TERMS:
        assert term not in lowered
    assert "blurry" in lowered
    assert "watermark" in lowered


def test_sfw_negative_contains_all_suppressing_terms():
    _, neg = prompt_mod.build("a person", None, nsfw=False)
    lowered = neg.lower()
    for term in prompt_mod.DEFAULT_NEGATIVE_SUPPRESSING_TERMS:
        assert term in lowered


def test_sfw_positive_lacks_nsfw_clause():
    pos, _ = prompt_mod.build("a person", None, nsfw=False)
    assert prompt_mod._NSFW_MARKER not in pos.lower()
    assert prompt_mod.NSFW_CLAUSE not in pos


def test_style_preset_appears_in_final_positive():
    pos, _ = prompt_mod.build("a person", None, nsfw=False, style_preset="anime style")
    assert "anime style" in pos


def test_gif_motion_clause_appended():
    result = prompt_mod.add_gif_motion_clause("a portrait of a calm engineer")
    assert "a portrait of a calm engineer" in result
    assert prompt_mod.GIF_MOTION_CLAUSE in result


def test_gif_motion_clause_not_duplicated_on_reapply():
    once = prompt_mod.add_gif_motion_clause("a portrait")
    twice = prompt_mod.add_gif_motion_clause(once)
    assert twice.count(prompt_mod._GIF_MOTION_MARKER) == 1


def test_gif_motion_clause_handles_empty_prompt():
    result = prompt_mod.add_gif_motion_clause("")
    assert result == prompt_mod.GIF_MOTION_CLAUSE


def test_nsfw_uses_local_clause_for_comfyui_and_no_backend():
    for backend in (None, "comfyui"):
        pos, _ = prompt_mod.build("a person", None, nsfw=True, backend=backend)
        assert prompt_mod.NSFW_CLAUSE_LOCAL in pos
        assert prompt_mod.NSFW_CLAUSE_HOSTED not in pos


def test_nsfw_uses_hosted_clause_for_chatgpt_grok_and_grok_cli():
    for backend in ("chatgpt", "grok", "grok-cli"):
        pos, _ = prompt_mod.build("a person", None, nsfw=True, backend=backend)
        assert prompt_mod.NSFW_CLAUSE_HOSTED in pos
        assert prompt_mod.NSFW_CLAUSE_LOCAL not in pos


def test_nsfw_hosted_clause_not_duplicated_on_regeneration():
    p1, _ = prompt_mod.build("a person", None, nsfw=True, backend="grok")
    p2, _ = prompt_mod.build(p1, None, nsfw=True, backend="grok")
    assert p2.count(prompt_mod._NSFW_MARKER_HOSTED) == 1


def test_nsfw_switching_backend_does_not_add_a_second_clause():
    # if the positive text already carries either clause (e.g. re-running with a different
    # backend choice), build() must not stack a second clause on top.
    local_first, _ = prompt_mod.build("a person", None, nsfw=True, backend="comfyui")
    combined, _ = prompt_mod.build(local_first, None, nsfw=True, backend="grok")
    assert combined.count(prompt_mod._NSFW_MARKER_LOCAL) == 1
    assert prompt_mod._NSFW_MARKER_HOSTED not in combined.lower()
