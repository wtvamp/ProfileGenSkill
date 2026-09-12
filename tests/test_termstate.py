import base64
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen import termstate  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("TERM_PROGRAM", "LC_TERMINAL", "TMUX", "TMUX_PANE"):
        monkeypatch.delenv(var, raising=False)


def test_detect_iterm_via_term_program(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    assert termstate.detect_iterm() is True


def test_detect_iterm_via_lc_terminal_inside_tmux(monkeypatch):
    # the case that matters: inside tmux, TERM_PROGRAM is rewritten to "tmux", and only
    # LC_TERMINAL still identifies the real outer terminal.
    monkeypatch.setenv("TERM_PROGRAM", "tmux")
    monkeypatch.setenv("LC_TERMINAL", "iTerm2")
    assert termstate.detect_iterm() is True


def test_detect_iterm_false_for_other_terminals(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "Apple_Terminal")
    assert termstate.detect_iterm() is False


def test_detect_iterm_false_when_nothing_set():
    assert termstate.detect_iterm() is False


def test_resolve_target_tty_none_when_stdout_is_a_tty(monkeypatch):
    monkeypatch.setattr(termstate.sys.stdout, "isatty", lambda: True)
    assert termstate.resolve_target_tty() is None


def test_resolve_target_tty_none_without_tmux(monkeypatch):
    monkeypatch.setattr(termstate.sys.stdout, "isatty", lambda: False)
    assert termstate.resolve_target_tty() is None


def test_resolve_target_tty_asks_tmux_for_the_pane_device(monkeypatch):
    monkeypatch.setattr(termstate.sys.stdout, "isatty", lambda: False)
    monkeypatch.setenv("TMUX", "/tmp/tmux-501/default,1,0")
    monkeypatch.setenv("TMUX_PANE", "%15")
    monkeypatch.setattr(termstate.shutil, "which", lambda name: "/usr/bin/tmux")

    def fake_run(cmd, capture_output, text, check, timeout):
        assert cmd[:2] == ["/usr/bin/tmux", "display-message"]
        assert "%15" in cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="/dev/ttys013\n")

    monkeypatch.setattr(termstate.subprocess, "run", fake_run)
    assert termstate.resolve_target_tty() == "/dev/ttys013"


def test_resolve_target_tty_none_when_tmux_call_fails(monkeypatch):
    monkeypatch.setattr(termstate.sys.stdout, "isatty", lambda: False)
    monkeypatch.setenv("TMUX", "/tmp/tmux-501/default,1,0")
    monkeypatch.setenv("TMUX_PANE", "%15")
    monkeypatch.setattr(termstate.shutil, "which", lambda name: "/usr/bin/tmux")

    def fake_run(cmd, capture_output, text, check, timeout):
        raise OSError("boom")

    monkeypatch.setattr(termstate.subprocess, "run", fake_run)
    assert termstate.resolve_target_tty() is None


def test_set_badge_writes_osc1337_to_target_file(tmp_path):
    target = tmp_path / "fake_tty"
    target.touch()
    assert termstate.set_badge("Ariel Reyes", str(target)) is True
    written = target.read_text(encoding="utf-8")
    assert written.startswith("\033]1337;SetBadgeFormat=")
    assert base64.b64encode(b"Ariel Reyes").decode() in written
    assert written.endswith("\a")


def test_set_background_image_writes_osc1337(tmp_path):
    target = tmp_path / "fake_tty"
    target.touch()
    assert termstate.set_background_image("/tmp/persona.png", str(target)) is True
    written = target.read_text(encoding="utf-8")
    assert "SetBackgroundImageFile=" in written
    assert base64.b64encode(b"/tmp/persona.png").decode() in written


def test_clear_helpers_send_empty_payloads(tmp_path):
    target = tmp_path / "fake_tty"
    target.touch()
    termstate.clear_badge(str(target))
    assert "SetBadgeFormat=\a" in target.read_text(encoding="utf-8")

    target.write_text("", encoding="utf-8")
    termstate.clear_background_image(str(target))
    assert "SetBackgroundImageFile=\a" in target.read_text(encoding="utf-8")


def test_sequences_are_tmux_wrapped_when_inside_tmux(tmp_path, monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/tmux-501/default,1,0")
    target = tmp_path / "fake_tty"
    target.touch()
    termstate.set_badge("X", str(target))
    written = target.read_text(encoding="utf-8")
    assert written.startswith("\033Ptmux;")
    assert written.endswith("\033\\")
    assert "\033\033]1337" in written  # ESC doubled for passthrough


def test_emit_failure_returns_false(tmp_path):
    missing_dir = tmp_path / "no-such-dir" / "tty"
    assert termstate.set_badge("X", str(missing_dir)) is False


def test_set_badge_to_stdout_when_tty_is_none(capsys):
    assert termstate.set_badge("Ariel Reyes", None) is True
    out = capsys.readouterr().out
    assert out.startswith("\033]1337;SetBadgeFormat=")
