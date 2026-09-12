import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen import hud  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(hud, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(hud, "BINARY", tmp_path / "persona-hud")
    monkeypatch.delenv("TMUX_PANE", raising=False)


def test_is_supported_requires_macos_and_swiftc(monkeypatch):
    monkeypatch.setattr(hud.sys, "platform", "darwin")
    monkeypatch.setattr(hud.shutil, "which", lambda name: "/usr/bin/swiftc")
    assert hud.is_supported() is True

    monkeypatch.setattr(hud.shutil, "which", lambda name: None)
    assert hud.is_supported() is False

    monkeypatch.setattr(hud.shutil, "which", lambda name: "/usr/bin/swiftc")
    monkeypatch.setattr(hud.sys, "platform", "win32")
    assert hud.is_supported() is False


def test_pane_key_isolates_sessions(monkeypatch):
    monkeypatch.setenv("TMUX_PANE", "%15")
    assert hud._pane_key() == "15"
    assert hud._pid_file().name == "hud-15.pid"

    monkeypatch.setenv("TMUX_PANE", "%7")
    assert hud._pid_file().name == "hud-7.pid"


def test_pane_key_falls_back_outside_tmux(monkeypatch):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    assert hud._pane_key() == "default"


def test_launch_noop_without_image_or_name(monkeypatch):
    # must not even attempt a build when there's nothing to show
    monkeypatch.setattr(hud, "ensure_built", lambda: (_ for _ in ()).throw(AssertionError("built")))
    assert hud.launch(None, None) is False


def test_launch_false_when_unsupported(monkeypatch):
    monkeypatch.setattr(hud, "ensure_built", lambda: None)
    assert hud.launch("/tmp/x.png", "Ada") is False


def test_launch_passes_tmux_pane_and_writes_pid(monkeypatch, tmp_path):
    binary = tmp_path / "persona-hud"
    binary.touch()
    monkeypatch.setattr(hud, "ensure_built", lambda: binary)
    monkeypatch.setenv("TMUX_PANE", "%15")
    monkeypatch.setattr(hud.shutil, "which", lambda name: "/usr/bin/tmux")

    captured = {}

    class FakeProcess:
        pid = 4242

    def fake_popen(args, **kwargs):
        captured["args"] = args
        assert kwargs["start_new_session"] is True
        return FakeProcess()

    monkeypatch.setattr(hud.subprocess, "Popen", fake_popen)
    assert hud.launch("/tmp/persona.png", "Ada Sterling") is True

    args = captured["args"]
    assert "--tmux-pane" in args and "%15" in args
    assert "--tmux-bin" in args and "/usr/bin/tmux" in args
    assert "--image" in args and "--name" in args
    assert (tmp_path / "hud-15.pid").read_text() == "4242"


def test_launch_omits_tmux_flags_outside_tmux(monkeypatch, tmp_path):
    binary = tmp_path / "persona-hud"
    binary.touch()
    monkeypatch.setattr(hud, "ensure_built", lambda: binary)
    monkeypatch.delenv("TMUX_PANE", raising=False)

    captured = {}

    class FakeProcess:
        pid = 99

    monkeypatch.setattr(
        hud.subprocess, "Popen", lambda args, **kw: (captured.update(args=args), FakeProcess())[1]
    )
    assert hud.launch("/tmp/persona.png", "Ada") is True
    assert "--tmux-pane" not in captured["args"]


def test_stop_only_targets_this_panes_pid(monkeypatch, tmp_path):
    (tmp_path / "hud-15.pid").write_text("4242")
    (tmp_path / "hud-7.pid").write_text("777")
    monkeypatch.setenv("TMUX_PANE", "%15")

    killed = []
    monkeypatch.setattr(hud.os, "kill", lambda pid, sig: killed.append(pid))

    assert hud.stop() is True
    assert killed == [4242]  # never 777 -- another session's persona
    assert not (tmp_path / "hud-15.pid").exists()
    assert (tmp_path / "hud-7.pid").exists()


def test_stop_false_when_nothing_running(monkeypatch):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    assert hud.stop() is False


def test_stop_clears_pid_file_even_if_process_already_gone(monkeypatch, tmp_path):
    (tmp_path / "hud-default.pid").write_text("4242")
    monkeypatch.delenv("TMUX_PANE", raising=False)

    def already_dead(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(hud.os, "kill", already_dead)
    assert hud.stop() is False
    assert not (tmp_path / "hud-default.pid").exists()


def test_ensure_built_skips_rebuild_when_binary_is_newer(monkeypatch, tmp_path):
    binary = tmp_path / "persona-hud"
    binary.write_text("stale-but-newer")
    monkeypatch.setattr(hud, "is_supported", lambda: True)

    def fail_build(*a, **kw):
        raise AssertionError("should not rebuild")

    monkeypatch.setattr(hud.subprocess, "run", fail_build)
    assert hud.ensure_built() == binary


def test_ensure_built_returns_none_on_compile_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(hud, "is_supported", lambda: True)
    monkeypatch.setattr(hud, "BINARY", tmp_path / "missing-binary")

    def failing(*a, **kw):
        raise subprocess.CalledProcessError(1, "swiftc")

    monkeypatch.setattr(hud.subprocess, "run", failing)
    assert hud.ensure_built() is None
