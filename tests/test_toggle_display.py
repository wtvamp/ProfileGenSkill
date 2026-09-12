import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from profilegen import frontmatter  # noqa: E402

_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6360000002000100"
    "56d0dd8f0000000049454e44ae426082"
)


def _run(args, cwd, env=None):
    return subprocess.run(
        [sys.executable, *args], capture_output=True, text=True, cwd=str(cwd), env=env
    )


def _write_profile(tmp_path, name, slug, output, assets):
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


def test_toggle_image_off_on_standalone_persona(tmp_path):
    write_result = _write_profile(tmp_path, "Ada Sterling", "ada-sterling", "claude-md-ref", "tracked")
    markdown_path = Path(write_result["markdown_path"])

    result = _run(
        ["scripts/toggle_display.py", "--root", str(tmp_path), "--image", "off"],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout)
    assert out["display"] == {"image": False, "name": True}

    content = markdown_path.read_text(encoding="utf-8")
    assert "image: false" in content
    assert "name: true" in content


def test_toggle_both_flags_at_once(tmp_path):
    write_result = _write_profile(tmp_path, "Rho", "rho", "claude-md-ref", "tracked")
    markdown_path = Path(write_result["markdown_path"])

    result = _run(
        ["scripts/toggle_display.py", "--root", str(tmp_path), "--image", "off", "--name", "off"],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout)
    assert out["display"] == {"image": False, "name": False}
    assert "image: false" in markdown_path.read_text(encoding="utf-8")


def test_toggle_no_flags_is_an_error(tmp_path):
    _write_profile(tmp_path, "Ada Sterling", "ada-sterling", "claude-md-ref", "tracked")
    result = _run(["scripts/toggle_display.py", "--root", str(tmp_path)], cwd=REPO_ROOT)
    assert result.returncode != 0
    assert "error" in json.loads(result.stdout)


def test_toggle_no_persona_found_is_an_error(tmp_path):
    result = _run(
        ["scripts/toggle_display.py", "--root", str(tmp_path), "--image", "off"], cwd=REPO_ROOT
    )
    assert result.returncode != 0
    assert "error" in json.loads(result.stdout)


def test_toggle_embedded_persona_scopes_to_its_own_slug(tmp_path):
    # two personas embedded in the same CLAUDE.md -- toggling one must not touch the other's block.
    _write_profile(tmp_path, "First Persona", "first-persona", "claude-md", "tracked")
    _write_profile(tmp_path, "Second Persona", "second-persona", "claude-md", "tracked")

    result = _run(
        [
            "scripts/toggle_display.py",
            "--root",
            str(tmp_path),
            "--slug",
            "first-persona",
            "--image",
            "off",
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout)
    assert out["slug"] == "first-persona"
    assert out["display"]["image"] is False

    claude_md_text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    first_block = frontmatter.extract_embedded_block(claude_md_text, "first-persona")
    second_block = frontmatter.extract_embedded_block(claude_md_text, "second-persona")
    assert first_block["display"]["image"] is False
    assert second_block["display"]["image"] is True  # untouched


def test_toggle_slug_filter_limits_to_one_persona_among_multiple_refs(tmp_path):
    _write_profile(tmp_path, "Ada Sterling", "ada-sterling", "claude-md-ref", "tracked")
    write_result_b = _write_profile(tmp_path, "Rho", "rho", "claude-md-ref", "tracked")

    result = _run(
        ["scripts/toggle_display.py", "--root", str(tmp_path), "--slug", "rho", "--name", "off"],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout)
    assert out["slug"] == "rho"

    rho_content = Path(write_result_b["markdown_path"]).read_text(encoding="utf-8")
    assert "name: false" in rho_content

    ada_path = tmp_path / "profiles" / "ada-sterling" / "ada-sterling.md"
    assert "name: true" in ada_path.read_text(encoding="utf-8")


def test_show_profile_reflects_toggled_state(tmp_path):
    _write_profile(tmp_path, "Ada Sterling", "ada-sterling", "claude-md-ref", "tracked")
    _run(["scripts/toggle_display.py", "--root", str(tmp_path), "--image", "off"], cwd=REPO_ROOT)

    env = dict(os.environ)
    env["TERM_PROGRAM"] = "iTerm.app"
    env.pop("TMUX", None)
    env.pop("KITTY_WINDOW_ID", None)

    result = _run(
        ["scripts/show_profile.py", "--root", str(tmp_path), "--mode", "inline"],
        cwd=REPO_ROOT,
        env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "\033]1337" not in result.stdout  # image stayed off
    assert "Ada Sterling" in result.stdout  # name still on
