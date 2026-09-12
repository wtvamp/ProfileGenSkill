import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import session_intro  # noqa: E402


def test_sanitized_project_key_matches_claude_code_mangling():
    root = Path("/Users/warrenthompson/Documents/GTD/Evidence/01_CASES/Thompson_v_Adoreal")
    assert (
        session_intro._sanitized_project_key(root)
        == "-Users-warrenthompson-Documents-GTD-Evidence-01-CASES-Thompson-v-Adoreal"
    )


def test_memory_activity_reads_memory_md(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    root = tmp_path / "proj"
    root.mkdir()
    key = session_intro._sanitized_project_key(root)
    memory_dir = tmp_path / "projects" / key / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text(
        "- [Thing one](thing-one.md) -- did a thing\n- [Thing two](thing-two.md) -- did another\n",
        encoding="utf-8",
    )
    assert session_intro._memory_activity(root) == (
        "- [Thing one](thing-one.md) -- did a thing\n- [Thing two](thing-two.md) -- did another"
    )


def test_memory_activity_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    root = tmp_path / "proj"
    root.mkdir()
    assert session_intro._memory_activity(root) is None


def test_recent_activity_prefers_memory_over_git(tmp_path, monkeypatch):
    monkeypatch.setattr(session_intro, "_memory_activity", lambda root: "memory line")
    monkeypatch.setattr(session_intro, "_git_activity", lambda root: "2026-01-01 a commit")
    activity, source = session_intro._recent_activity(tmp_path)
    assert (activity, source) == ("memory line", "memory")


def test_recent_activity_falls_back_to_git(tmp_path, monkeypatch):
    monkeypatch.setattr(session_intro, "_memory_activity", lambda root: None)
    monkeypatch.setattr(session_intro, "_git_activity", lambda root: "2026-01-01 a commit")
    activity, source = session_intro._recent_activity(tmp_path)
    assert (activity, source) == ("2026-01-01 a commit", "git")


def test_recent_activity_none_when_both_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(session_intro, "_memory_activity", lambda root: None)
    monkeypatch.setattr(session_intro, "_git_activity", lambda root: None)
    activity, source = session_intro._recent_activity(tmp_path)
    assert (activity, source) == (None, "none")


def test_build_context_labels_memory_source():
    context = session_intro.build_context("Ada", None, "- [Thing](thing.md) -- did it", "memory")
    assert "own memory of past sessions" in context
    assert "Recent commits" not in context


def test_build_context_labels_git_fallback():
    context = session_intro.build_context("Ada", None, "2026-01-01 did a thing", "git")
    assert "no session memory exists yet" in context
    assert "Recent commits" in context


def test_first_activity_teaser_from_memory_strips_markdown():
    teaser = session_intro._first_activity_teaser(
        "- [Voice dictation feature](voice.md) — orb mic, local STT", "memory"
    )
    assert teaser == "Voice dictation feature"


def test_first_activity_teaser_from_git():
    teaser = session_intro._first_activity_teaser("2026-01-01 Fix the thing", "git")
    assert teaser == "Fix the thing"


def test_build_system_message_uses_teaser():
    message = session_intro.build_system_message("Ada", "2026-01-01 Fix the thing", "git")
    assert message == "👋 Ada here. Lately: Fix the thing."


def test_build_system_message_none_when_nothing_known():
    assert session_intro.build_system_message(None, None, "none") is None
