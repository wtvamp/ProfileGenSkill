import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


def test_full_offline_pipeline_with_mock_backend(tmp_path):
    # 1. config sanity check
    result = _run(["scripts/check_config.py", "--backend", "mock"], cwd=REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr
    check = json.loads(result.stdout)
    assert check["ok"] is True

    # 2. plan output paths
    result = _run(
        [
            "scripts/write_profile.py",
            "--plan-only",
            "--name",
            "Test Persona",
            "--root",
            str(tmp_path),
            "--output",
            "file",
            "--assets",
            "gitignored",
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    plan = json.loads(result.stdout)
    asset_dir = Path(plan["asset_dir"])
    asset_dir.mkdir(parents=True, exist_ok=True)

    # 3. generate the still image -- the SFW variant, which every persona has
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("a friendly test persona", encoding="utf-8")
    image_path = asset_dir / "test-persona.png"

    result = _run(
        [
            "scripts/generate_image.py",
            "--backend",
            "mock",
            "--prompt-file",
            str(prompt_file),
            "--out",
            str(image_path),
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    image_result = json.loads(result.stdout)
    actual_image_path = Path(image_result["path"])
    assert actual_image_path.exists()

    try:
        from PIL import Image

        img = Image.open(actual_image_path).convert("RGB")
        colors = img.getcolors(maxcolors=1_000_000)
        assert colors is None or len(colors) > 1
    except ImportError:
        assert actual_image_path.stat().st_size > 0

    # 3b. generate the optional NSFW variant: same seed and base prompt, --nsfw added, so the
    # two pictures are the same character rather than two different ones.
    nsfw_image_path = asset_dir / "test-persona-nsfw.png"
    result = _run(
        [
            "scripts/generate_image.py",
            "--backend",
            "mock",
            "--nsfw",
            "--prompt-file",
            str(prompt_file),
            "--seed",
            str(image_result["seed"]),
            "--out",
            str(nsfw_image_path),
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    nsfw_image_result = json.loads(result.stdout)
    assert Path(nsfw_image_result["path"]).exists()
    assert nsfw_image_result["seed"] == image_result["seed"]

    # 4. generate the gif (synthetic, since mock has no native gif support)
    gif_path = asset_dir / "test-persona.gif"
    result = _run(
        [
            "scripts/make_gif.py",
            "--backend",
            "mock",
            "--png",
            str(actual_image_path),
            "--out",
            str(gif_path),
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    gif_result = json.loads(result.stdout)
    assert gif_result["mode"] == "synthetic"
    assert Path(gif_result["path"]).exists()

    # 5. write the profile -- one file per variant: the GIF replaces the PNG as `image` since one
    # was generated (there's no separate animated-image field), and the NSFW still goes in
    # `image_nsfw`. Top-level `nsfw` is derived from image_nsfw, so it isn't passed here.
    fields = {
        "schema_version": 1,
        "name": "Test Persona",
        "slug": "test-persona",
        "image": gif_result["path"],
        "image_nsfw": nsfw_image_result["path"],
        "voice": "jessica",
        "personality": "Warm, direct, curious.",
        "generation": {
            "backend": "mock",
            "model": image_result["model"],
            "prompt": "a friendly test persona",
            "negative_prompt": None,
            "seed": image_result["seed"],
            "gif_mode": gif_result["mode"],
            "created_at": "2026-01-01T00:00:00Z",
        },
    }
    fields_file = tmp_path / "fields.json"
    fields_file.write_text(json.dumps(fields), encoding="utf-8")

    result = _run(
        [
            "scripts/write_profile.py",
            "--fields-file",
            str(fields_file),
            "--root",
            str(tmp_path),
            "--output",
            "file",
            "--assets",
            "gitignored",
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    write_result = json.loads(result.stdout)
    assert Path(write_result["markdown_path"]).exists()
    assert write_result["gitignore_updated"] is True
    assert write_result["image_path"] == gif_result["path"]
    assert write_result["image_nsfw_path"] == nsfw_image_result["path"]
    assert "gif_path" not in write_result

    # a persona with both pictures starts on the SFW one, with nsfw derived as true
    profile_text = Path(write_result["markdown_path"]).read_text(encoding="utf-8")
    assert "nsfw: true" in profile_text
    assert "variant: sfw" in profile_text
    # pictures are recorded relative to the project root, as the schema says -- Claude Buddy
    # refuses a rooted persona picture, so an absolute path here put the wrong face on an orb
    def rel(p):
        return Path(p).resolve().relative_to(tmp_path.resolve()).as_posix()
    assert f'image_nsfw: "{rel(nsfw_image_result["path"])}"' in profile_text
    assert nsfw_image_result["path"] not in profile_text
    # ...and the visible markdown picture is the SFW one, never the explicit variant
    assert f"![Test Persona]({rel(gif_result['path'])})" in profile_text

    gitignore_path = tmp_path / ".gitignore"
    assert gitignore_path.exists()
    assert ".profiles-assets/" in gitignore_path.read_text(encoding="utf-8")


def test_private_persona_via_claude_md_ref_leaks_no_identity(tmp_path):
    """--output claude-md-ref --assets gitignored: CLAUDE.md must end up with only a fixed,
    generic @-import -- never the persona's actual name -- while the persona's own gitignored
    file carries the real content.
    """
    persona_name = "Sienna Foxx"

    result = _run(
        [
            "scripts/write_profile.py",
            "--plan-only",
            "--name",
            persona_name,
            "--root",
            str(tmp_path),
            "--output",
            "claude-md-ref",
            "--assets",
            "gitignored",
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    plan = json.loads(result.stdout)
    asset_dir = Path(plan["asset_dir"])
    assert asset_dir == tmp_path / ".claude" / "persona"
    asset_dir.mkdir(parents=True, exist_ok=True)

    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("a private test persona", encoding="utf-8")
    image_path = asset_dir / "persona.png"
    nsfw_image_path = asset_dir / "persona-nsfw.png"

    result = _run(
        [
            "scripts/generate_image.py",
            "--backend",
            "mock",
            "--prompt-file",
            str(prompt_file),
            "--out",
            str(image_path),
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    image_result = json.loads(result.stdout)

    result = _run(
        [
            "scripts/generate_image.py",
            "--backend",
            "mock",
            "--nsfw",
            "--prompt-file",
            str(prompt_file),
            "--out",
            str(nsfw_image_path),
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    nsfw_image_result = json.loads(result.stdout)

    fields = {
        "schema_version": 1,
        "name": persona_name,
        "slug": "sienna-foxx",
        "image": image_result["path"],
        "image_nsfw": nsfw_image_result["path"],
        "personality": "Wry, private, unmistakably herself.",
        "generation": {
            "backend": "mock",
            "model": image_result["model"],
            "prompt": "a private test persona",
            "negative_prompt": None,
            "seed": image_result["seed"],
            "gif_mode": None,
            "created_at": "2026-01-01T00:00:00Z",
        },
    }
    fields_file = tmp_path / "fields.json"
    fields_file.write_text(json.dumps(fields), encoding="utf-8")

    result = _run(
        [
            "scripts/write_profile.py",
            "--fields-file",
            str(fields_file),
            "--root",
            str(tmp_path),
            "--output",
            "claude-md-ref",
            "--assets",
            "gitignored",
        ],
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    write_result = json.loads(result.stdout)

    assert write_result["markdown_path"] == str(tmp_path / ".claude" / "persona" / "persona.md")
    assert write_result["claude_md_path"] == str(tmp_path / "CLAUDE.md")
    assert write_result["gitignore_updated"] is True

    claude_md_content = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert "@.claude/persona/persona.md" in claude_md_content
    # the whole point: nothing about the persona's identity leaks into the tracked file
    assert "Sienna" not in claude_md_content
    assert "sienna" not in claude_md_content.lower()
    assert "Wry, private" not in claude_md_content

    gitignore_content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".claude/persona/" in gitignore_content

    persona_md_content = Path(write_result["markdown_path"]).read_text(encoding="utf-8")
    assert "Sienna Foxx" in persona_md_content
    assert "Wry, private" in persona_md_content
