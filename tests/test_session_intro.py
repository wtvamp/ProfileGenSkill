import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import session_intro  # noqa: E402


def _touch(path: Path, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("content", encoding="utf-8")
    os.utime(path, (mtime, mtime))


def test_recent_files_activity_orders_newest_first(tmp_path):
    now = time.time()
    _touch(tmp_path / "old.md", now - 100)
    _touch(tmp_path / "sub" / "new.md", now)
    activity = session_intro._recent_files_activity(tmp_path)
    lines = activity.splitlines()
    assert lines[0].endswith("sub/new.md") or lines[0].endswith("sub\\new.md")
    assert lines[1].endswith("old.md")


def test_recent_files_activity_skips_hidden_and_noise_dirs(tmp_path):
    now = time.time()
    _touch(tmp_path / ".git" / "HEAD", now)
    _touch(tmp_path / "node_modules" / "pkg" / "index.js", now)
    _touch(tmp_path / ".hidden_file", now)
    _touch(tmp_path / "real_work.md", now - 1)
    activity = session_intro._recent_files_activity(tmp_path)
    assert activity is not None
    assert "real_work.md" in activity
    assert ".git" not in activity
    assert "node_modules" not in activity
    assert ".hidden_file" not in activity


def test_recent_files_activity_none_for_empty_dir(tmp_path):
    assert session_intro._recent_files_activity(tmp_path) is None


def test_recent_activity_prefers_files_over_git(tmp_path, monkeypatch):
    monkeypatch.setattr(session_intro, "_recent_files_activity", lambda root: "2026-01-01  a.md")
    monkeypatch.setattr(session_intro, "_git_activity", lambda root: "2026-01-01 a commit")
    activity, source = session_intro._recent_activity(tmp_path)
    assert (activity, source) == ("2026-01-01  a.md", "files")


def test_recent_activity_falls_back_to_git(tmp_path, monkeypatch):
    monkeypatch.setattr(session_intro, "_recent_files_activity", lambda root: None)
    monkeypatch.setattr(session_intro, "_git_activity", lambda root: "2026-01-01 a commit")
    activity, source = session_intro._recent_activity(tmp_path)
    assert (activity, source) == ("2026-01-01 a commit", "git")


def test_recent_activity_none_when_both_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(session_intro, "_recent_files_activity", lambda root: None)
    monkeypatch.setattr(session_intro, "_git_activity", lambda root: None)
    activity, source = session_intro._recent_activity(tmp_path)
    assert (activity, source) == (None, "none")


def test_build_context_labels_files_source_and_warns_against_inventing_a_narrative():
    context = session_intro.build_context("Ada", None, "2026-01-01  a.md", "files")
    assert "most recently touched" in context.lower()
    assert "don't invent details" in context
    assert "Recent commits" not in context


def test_build_context_labels_git_fallback():
    context = session_intro.build_context("Ada", None, "2026-01-01 did a thing", "git")
    assert "no useful file-recency signal" in context
    assert "Recent commits" in context


def test_first_activity_teaser_from_files():
    teaser = session_intro._first_activity_teaser("2026-01-01  notes/plan.md", "files")
    assert teaser == "notes/plan.md"


def test_first_activity_teaser_from_git():
    teaser = session_intro._first_activity_teaser("2026-01-01 Fix the thing", "git")
    assert teaser == "Fix the thing"


def test_build_system_message_uses_files_teaser():
    message = session_intro.build_system_message("Ada", "2026-01-01  notes/plan.md", "files")
    assert message == "👋 Ada here. Most recently touched: notes/plan.md."


def test_build_system_message_uses_git_teaser():
    message = session_intro.build_system_message("Ada", "2026-01-01 Fix the thing", "git")
    assert message == "👋 Ada here. Lately: Fix the thing."


def test_build_system_message_none_when_nothing_known():
    assert session_intro.build_system_message(None, None, "none") is None
