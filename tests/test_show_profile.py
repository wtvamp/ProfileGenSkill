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


def _write_profile(tmp_path, name, slug, output, assets, display=None, with_nsfw=False):
    fields = {
        "schema_version": 1,
        "name": name,
        "slug": slug,
        "image": f"{slug}.png",
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
    if with_nsfw:
        fields["image_nsfw"] = f"{slug}-nsfw.png"
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
    if write_result.get("image_nsfw_path"):
        (tmp_path / write_result["image_nsfw_path"]).write_bytes(_TINY_PNG)
    return write_result


def _show(tmp_path, *extra, env=None):
    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path), "--mode", "state", *extra],
        cwd=REPO_ROOT,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result, json.loads(result.stdout.strip().splitlines()[-1])


def test_show_defaults_to_the_sfw_picture(tmp_path, force_iterm_env):
    _write_profile(tmp_path, "Vera Lux", "vera-lux", "claude-md-ref", "tracked", with_nsfw=True)
    _, report = _show(tmp_path, env=force_iterm_env)
    assert report["variant"] == "sfw"
    assert report["variant_fell_back"] is False


def test_variant_flag_overrides_the_stored_preference_without_changing_it(
    tmp_path, force_iterm_env
):
    write_result = _write_profile(
        tmp_path, "Vera Lux", "vera-lux", "claude-md-ref", "tracked", with_nsfw=True
    )
    sfw_result, sfw_report = _show(tmp_path, env=force_iterm_env)
    nsfw_result, nsfw_report = _show(tmp_path, "--variant", "nsfw", env=force_iterm_env)

    assert sfw_report["variant"] == "sfw"
    assert nsfw_report["variant"] == "nsfw"
    # a different picture really was handed to the terminal, not just a different label
    assert sfw_result.stdout != nsfw_result.stdout
    # ...and the stored preference is untouched by a display-time override
    assert "variant: sfw" in Path(write_result["markdown_path"]).read_text(encoding="utf-8")


def test_stored_nsfw_variant_is_what_gets_shown(tmp_path, force_iterm_env):
    _write_profile(
        tmp_path,
        "Vera Lux",
        "vera-lux",
        "claude-md-ref",
        "tracked",
        display={"image": True, "name": True, "autostart": True, "variant": "nsfw"},
        with_nsfw=True,
    )
    _, report = _show(tmp_path, env=force_iterm_env)
    assert report["variant"] == "nsfw"


def test_asking_for_nsfw_on_a_sfw_only_persona_falls_back_rather_than_showing_nothing(
    tmp_path, force_iterm_env
):
    _write_profile(tmp_path, "Plain Jane", "plain-jane", "claude-md-ref", "tracked")
    _, report = _show(tmp_path, "--variant", "nsfw", env=force_iterm_env)
    assert report["requested_variant"] == "nsfw"
    assert report["variant"] == "sfw"
    assert report["variant_fell_back"] is True
    assert report["background"] is True


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
        ["scripts/show_profile.py", "--root", str(tmp_path), "--mode", "inline"],
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
        ["scripts/show_profile.py", "--root", str(tmp_path), "--mode", "inline"],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # nothing is drawn -- no image escape sequence, no printed name. The JSON report still says
    # so, which is what a calling program needs to distinguish "off" from "failed".
    assert "\033]1337" not in result.stdout
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["inline"] is False
    assert report["badge"] is False


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
        ["scripts/show_profile.py", "--root", str(tmp_path), "--mode", "inline", "--show-name"],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Quiet Persona" in result.stdout


def test_show_profile_no_claude_md_is_silent_noop(tmp_path, force_iterm_env):
    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path), "--mode", "inline"],
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
    for var in ("TERM_PROGRAM", "KITTY_WINDOW_ID", "TMUX", "LC_TERMINAL"):
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


def test_state_mode_emits_badge_and_background(tmp_path, force_iterm_env):
    _write_profile(tmp_path, "Ada Sterling", "ada-sterling", "claude-md-ref", "tracked")
    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path), "--mode", "state"],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SetBadgeFormat=" in result.stdout
    assert "SetBackgroundImageFile=" in result.stdout
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["mode"] == "state"
    assert report["badge"] is True
    assert report["background"] is True


def test_state_mode_respects_display_flags(tmp_path, force_iterm_env):
    _write_profile(
        tmp_path,
        "Quiet Persona",
        "quiet-persona",
        "claude-md-ref",
        "tracked",
        display={"image": False, "name": True},
    )
    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path), "--mode", "state"],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["badge"] is True
    assert report["background"] is False


@pytest.mark.skipif(sys.platform != "darwin", reason="hud overlay is macOS-only")
def test_auto_mode_picks_hud_on_macos(tmp_path, force_iterm_env):
    # both display flags off, so the mode is still selected but no overlay window is spawned --
    # a test run must not leave a floating window on the developer's screen.
    _write_profile(
        tmp_path,
        "Ada Sterling",
        "ada-sterling",
        "claude-md-ref",
        "tracked",
        display={"image": False, "name": False},
    )
    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path)], cwd=REPO_ROOT, env=force_iterm_env
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["mode"] == "hud"
    assert report["hud"] is False


def test_auto_never_picks_state_which_overwrites_user_settings(tmp_path):
    # `state` sets iTerm2's background image, which belongs to the user -- it must stay opt-in
    # even when iTerm2 is unmistakably the terminal.
    _write_profile(
        tmp_path,
        "Ada Sterling",
        "ada-sterling",
        "claude-md-ref",
        "tracked",
        display={"image": False, "name": False},
    )
    env = dict(os.environ)
    env["TERM_PROGRAM"] = "tmux"
    env["LC_TERMINAL"] = "iTerm2"
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)
    result = _run(["scripts/show_profile.py", "--root", str(tmp_path)], cwd=REPO_ROOT, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["mode"] != "state"


def test_auto_mode_falls_back_to_inline_without_iterm(tmp_path):
    _write_profile(tmp_path, "Ada Sterling", "ada-sterling", "claude-md-ref", "tracked")
    env = dict(os.environ)
    for var in ("TERM_PROGRAM", "LC_TERMINAL", "KITTY_WINDOW_ID", "TMUX"):
        env.pop(var, None)
    env["TERM"] = "xterm-256color"
    env["PATH"] = "/nonexistent"
    result = _run(["scripts/show_profile.py", "--root", str(tmp_path)], cwd=REPO_ROOT, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["mode"] == "inline"


def test_clear_removes_badge_and_background(tmp_path, force_iterm_env):
    # Point HOME at the tmp dir so hud.CACHE_DIR resolves there: otherwise this subprocess
    # inherits the real HOME and TMUX_PANE and would stop the developer's own running overlay.
    env = dict(force_iterm_env)
    env["HOME"] = str(tmp_path)
    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path), "--clear"],
        cwd=REPO_ROOT,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SetBadgeFormat=\a" in result.stdout
    assert "SetBackgroundImageFile=\a" in result.stdout
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["cleared_badge"] is True
    assert report["cleared_background"] is True


def test_off_mode_draws_nothing(tmp_path, force_iterm_env):
    _write_profile(tmp_path, "Ada Sterling", "ada-sterling", "claude-md-ref", "tracked")
    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path), "--mode", "off"],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""


def test_show_profile_explicit_profile_flag_skips_claude_md(tmp_path, force_iterm_env):
    write_result = _write_profile(tmp_path, "Ada Sterling", "ada-sterling", "file", "tracked")
    result = _run(
        [
            "scripts/show_profile.py",
            "--root",
            str(tmp_path),
            "--mode",
            "inline",
            "--profile",
            write_result["markdown_path"],
        ],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Ada Sterling" in result.stdout


def test_autostart_only_skips_persona_with_autostart_off(tmp_path, force_iterm_env):
    _write_profile(
        tmp_path,
        "Quiet Starter",
        "quiet-starter",
        "claude-md-ref",
        "tracked",
        display={"image": True, "name": True, "autostart": False},
    )
    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path), "--mode", "inline", "--autostart-only"],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""  # nothing displayed, nothing reported


def test_without_autostart_only_the_same_persona_still_displays(tmp_path, force_iterm_env):
    # autostart governs only automatic display -- asking for it explicitly must still work
    _write_profile(
        tmp_path,
        "Quiet Starter",
        "quiet-starter",
        "claude-md-ref",
        "tracked",
        display={"image": True, "name": True, "autostart": False},
    )
    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path), "--mode", "inline"],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Quiet Starter" in result.stdout


def test_autostart_only_shows_persona_with_autostart_on(tmp_path, force_iterm_env):
    _write_profile(
        tmp_path,
        "Eager Starter",
        "eager-starter",
        "claude-md-ref",
        "tracked",
        display={"image": False, "name": True, "autostart": True},
    )
    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path), "--mode", "inline", "--autostart-only"],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Eager Starter" in result.stdout


def test_autostart_defaults_to_on_for_a_profile_predating_the_field(tmp_path, force_iterm_env):
    # an older persona has no autostart key; it must keep appearing at startup, not silently stop
    _write_profile(tmp_path, "Legacy Persona", "legacy-persona", "claude-md-ref", "tracked")
    persona = tmp_path / "profiles" / "legacy-persona" / "legacy-persona.md"
    persona.write_text(
        persona.read_text(encoding="utf-8").replace("  autostart: true\n", ""), encoding="utf-8"
    )
    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path), "--mode", "inline", "--autostart-only"],
        cwd=REPO_ROOT,
        env=force_iterm_env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Legacy Persona" in result.stdout
