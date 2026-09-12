import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen import termimg  # noqa: E402

# A minimal valid 1x1 PNG (transparent pixel) -- real bytes, so base64-encoding/reading them
# exercises the actual code path rather than an empty placeholder.
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6360000002000100"
    "56d0dd8f0000000049454e44ae426082"
)


@pytest.fixture(autouse=True)
def _no_tmux_leak(monkeypatch):
    # the real dev/CI shell this test suite runs in may itself be inside tmux -- clear it so
    # tmux-passthrough wrapping is opt-in per test (test_wrap_tmux_* set it back deliberately).
    monkeypatch.delenv("TMUX", raising=False)


@pytest.fixture
def clean_env(monkeypatch):
    for var in ("TERM_PROGRAM", "KITTY_WINDOW_ID", "TERM", "TMUX"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(termimg.shutil, "which", lambda name: None)


def test_detect_protocol_iterm(clean_env, monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    assert termimg.detect_protocol() == "iterm"


def test_detect_protocol_wezterm(clean_env, monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "WezTerm")
    assert termimg.detect_protocol() == "iterm"


def test_detect_protocol_kitty_via_window_id(clean_env, monkeypatch):
    monkeypatch.setenv("KITTY_WINDOW_ID", "1")
    assert termimg.detect_protocol() == "kitty"


def test_detect_protocol_kitty_via_term(clean_env, monkeypatch):
    monkeypatch.setenv("TERM", "xterm-kitty")
    assert termimg.detect_protocol() == "kitty"


def test_detect_protocol_sixel_fallback(clean_env, monkeypatch):
    monkeypatch.setattr(termimg.shutil, "which", lambda name: "/usr/bin/img2sixel" if name == "img2sixel" else None)
    assert termimg.detect_protocol() == "sixel"


def test_detect_protocol_none_when_nothing_matches(clean_env):
    assert termimg.detect_protocol() is None


def test_wrap_tmux_passthrough_when_set(monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1234,0")
    wrapped = termimg._wrap_tmux("\033]hello\a")
    assert wrapped.startswith("\033Ptmux;")
    assert wrapped.endswith("\033\\")
    assert "\033\033]hello\a" in wrapped


def test_wrap_tmux_noop_when_unset(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    assert termimg._wrap_tmux("\033]hello\a") == "\033]hello\a"


def test_target_cells_uses_width_pct_of_columns(monkeypatch):
    monkeypatch.setattr(termimg.shutil, "get_terminal_size", lambda fallback=(80, 24): (100, 40))
    cols, rows = termimg._target_cells(10)
    assert cols == 10
    assert rows == 5


def test_target_cells_floors_at_one_cell(monkeypatch):
    monkeypatch.setattr(termimg.shutil, "get_terminal_size", lambda fallback=(80, 24): (1, 24))
    cols, rows = termimg._target_cells(1)
    assert cols == 1
    assert rows == 1


def test_display_image_missing_file_returns_false(tmp_path):
    assert termimg.display_image(tmp_path / "nope.png", protocol="iterm") is False


def test_display_image_none_protocol_returns_false(tmp_path):
    png = tmp_path / "p.png"
    png.write_bytes(_TINY_PNG)
    assert termimg.display_image(png, protocol=None) is False


def test_display_image_iterm_writes_osc_1337(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    png = tmp_path / "p.png"
    png.write_bytes(_TINY_PNG)
    assert termimg.display_image(png, width_pct=10, protocol="iterm") is True
    out = capsys.readouterr().out
    assert out.startswith("\033]1337;File=inline=1;width=10%")
    assert out.endswith("\a")


def test_display_image_kitty_raw_fallback_writes_apc(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(termimg.shutil, "which", lambda name: None)  # no kitten/icat on PATH
    monkeypatch.setattr(termimg.shutil, "get_terminal_size", lambda fallback=(80, 24): (80, 24))
    png = tmp_path / "p.png"
    png.write_bytes(_TINY_PNG)
    assert termimg.display_image(png, width_pct=10, protocol="kitty") is True
    out = capsys.readouterr().out
    assert out.startswith("\033_G")
    assert "a=T,f=100" in out


def test_display_image_kitty_raw_fallback_skips_gif(tmp_path, monkeypatch):
    monkeypatch.setattr(termimg.shutil, "which", lambda name: None)
    gif = tmp_path / "p.gif"
    gif.write_bytes(b"GIF89a")
    assert termimg.display_image(gif, protocol="kitty") is False


def test_display_image_kitty_prefers_helper_binary(tmp_path, monkeypatch):
    calls = []

    def fake_which(name):
        return "/usr/bin/kitten" if name == "kitten" else None

    def fake_run(cmd, check):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(termimg.shutil, "which", fake_which)
    monkeypatch.setattr(termimg.subprocess, "run", fake_run)
    png = tmp_path / "p.png"
    png.write_bytes(_TINY_PNG)
    assert termimg.display_image(png, protocol="kitty") is True
    assert calls and calls[0][0] == "/usr/bin/kitten"
    assert calls[0][1] == "icat"


def test_display_image_sixel_invokes_img2sixel(tmp_path, monkeypatch):
    def fake_run(cmd, capture_output, check):
        assert cmd[0] == "img2sixel"
        return subprocess.CompletedProcess(cmd, 0, stdout=b"\033Pq...sixel-data...\033\\")

    monkeypatch.setattr(termimg.subprocess, "run", fake_run)
    png = tmp_path / "p.png"
    png.write_bytes(_TINY_PNG)
    assert termimg.display_image(png, protocol="sixel") is True


def test_display_image_sixel_missing_binary_returns_false(tmp_path, monkeypatch):
    def fake_run(cmd, capture_output, check):
        raise FileNotFoundError()

    monkeypatch.setattr(termimg.subprocess, "run", fake_run)
    png = tmp_path / "p.png"
    png.write_bytes(_TINY_PNG)
    assert termimg.display_image(png, protocol="sixel") is False
