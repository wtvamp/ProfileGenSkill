import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6360000002000100"
    "56d0dd8f0000000049454e44ae426082"
)


def _run(args, cwd, env=None):
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=env,
    )


def _write_profile(tmp_path, name, slug, output, assets, display=None):
    fields = {
        "schema_version": 1,
        "name": name,
        "slug": slug,
        "image": f"{slug}.png",
        "nsfw": False,
        "generation": {
            "backend": "mock",
            "model": "mock-v1",
            "prompt": "portrait",
            "negative_prompt": None,
            "seed": 1,
            "gif_mode": None,
            "created_at": "2026-01-01T00:00:00Z",
        },
    }
    if display is not None:
        fields["display"] = display
    fields_file = tmp_path / f"{slug}-fields.json"
    fields_file.write_text(json.dumps(fields), encoding="utf-8")

    result = _run(
        [
            "scripts/write_profile.py",
            "--fields-file",
            str(fields_file),
            "--root",
            str(tmp_path),
            "--output",
            output,
            "--assets",
            assets,
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    write_result = json.loads(result.stdout)
    (tmp_path / write_result["image_path"]).write_bytes(_TINY_PNG)
    return write_result


def test_write_profile_defaults_display_to_true_true(tmp_path):
    write_result = _write_profile(tmp_path, "Ada Sterling", "ada-sterling", "file", "tracked")
    content = Path(write_result["markdown_path"]).read_text(encoding="utf-8")
    assert "display:" in content
    assert "image: true" in content
    assert "name: true" in content


def test_write_profile_preserves_explicit_display_off(tmp_path):
    write_result = _write_profile(
        tmp_path, "Rho", "rho", "file", "tracked", display={"image": False, "name": True}
    )
    content = Path(write_result["markdown_path"]).read_text(encoding="utf-8")
    assert "image: false" in content
    assert "name: true" in content


@pytest.fixture
def force_iterm_env():
    env = dict(**os.environ)
    env["TERM_PROGRAM"] = "iTerm.app"
    env.pop("TMUX", None)
    env.pop("KITTY_WINDOW_ID", None)
    return env


def test_show_profile_discovers_and_displays_claude_md_ref_persona(tmp_path, force_iterm_env):
    write_result = _write_profile(
        tmp_path, "Ada Sterling", "ada-sterling", "claude-md-ref", "tracked"
    )
    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()

    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path)],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "\033]1337;File=inline=1;width=10%" in result.stdout
    assert "Ada Sterling" in result.stdout


def test_show_profile_respects_stored_display_off(tmp_path, force_iterm_env):
    _write_profile(
        tmp_path,
        "Quiet Persona",
        "quiet-persona",
        "claude-md-ref",
        "tracked",
        display={"image": False, "name": False},
    )
    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path)],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""


def test_show_profile_cli_override_beats_stored_preference(tmp_path, force_iterm_env):
    _write_profile(
        tmp_path,
        "Quiet Persona",
        "quiet-persona",
        "claude-md-ref",
        "tracked",
        display={"image": False, "name": False},
    )
    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path), "--show-name"],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Quiet Persona" in result.stdout


def test_show_profile_no_claude_md_is_silent_noop(tmp_path, force_iterm_env):
    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path)],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""


def test_show_profile_unsupported_terminal_shows_name_only(tmp_path):
    write_result = _write_profile(
        tmp_path, "Ada Sterling", "ada-sterling", "claude-md-ref", "tracked"
    )
    env = dict(**os.environ)
    for var in ("TERM_PROGRAM", "KITTY_WINDOW_ID", "TMUX"):
        env.pop(var, None)
    env["TERM"] = "xterm-256color"
    env["PATH"] = "/nonexistent"  # ensure img2sixel isn't "found" via a leftover PATH entry

    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path)],
        cwd=REPO_ROOT,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Ada Sterling" in result.stdout
    assert "\033]1337" not in result.stdout
    assert "\033_G" not in result.stdout


def test_show_profile_explicit_profile_flag_skips_claude_md(tmp_path, force_iterm_env):
    write_result = _write_profile(tmp_path, "Ada Sterling", "ada-sterling", "file", "tracked")
    result = _run(
        [
            "scripts/show_profile.py",
            "--root",
            str(tmp_path),
            "--profile",
            write_result["markdown_path"],
        ],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Ada Sterling" in result.stdout
