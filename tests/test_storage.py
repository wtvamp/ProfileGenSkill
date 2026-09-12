import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen import storage  # noqa: E402


def test_slugify():
    assert storage.slugify("Ada Sterling") == "ada-sterling"
    assert storage.slugify("  Weird!! Name_2  ") == "weird-name-2"
    assert storage.slugify("") == "profile"


@pytest.mark.parametrize(
    "output,assets,expected_markdown,expected_asset_dir,expected_marker_key",
    [
        ("file", "tracked", "profiles/ada/ada.md", "profiles/ada", "ada"),
        (
            "file",
            "gitignored",
            ".profiles-assets/ada/ada.md",
            ".profiles-assets/ada",
            "ada",
        ),
        ("claude-md-ref", "tracked", "profiles/ada/ada.md", "profiles/ada", "ada"),
        # gitignored + claude-md-ref is the private combo: fixed, generic path -- never
        # derived from the slug -- so the tracked @-import string can't reveal identity.
        (
            "claude-md-ref",
            "gitignored",
            ".claude/persona/persona.md",
            ".claude/persona",
            "persona",
        ),
        ("claude-md", "tracked", "CLAUDE.md", "profiles/ada", "ada"),
        ("claude-md", "gitignored", "CLAUDE.md", ".profiles-assets/ada", "ada"),
    ],
)
def test_plan_paths_all_combos(
    tmp_path, output, assets, expected_markdown, expected_asset_dir, expected_marker_key
):
    paths = storage.plan_paths(tmp_path, "ada", output, assets)
    assert paths["markdown_path"] == str(tmp_path / expected_markdown)
    assert paths["asset_dir"] == str(tmp_path / expected_asset_dir)
    assert paths["marker_key"] == expected_marker_key


def test_private_reference_path_is_identical_regardless_of_persona_name(tmp_path):
    # the whole point: the fixed path must not vary with the persona's actual name.
    paths_a = storage.plan_paths(tmp_path, "sienna-foxx", "claude-md-ref", "gitignored")
    paths_b = storage.plan_paths(tmp_path, "marcus-vale", "claude-md-ref", "gitignored")
    assert paths_a == paths_b
    assert "sienna" not in paths_a["markdown_path"]
    assert "marcus" not in paths_b["markdown_path"]


def test_gitignore_pattern_for_private_combo_is_scoped_to_claude_persona():
    assert storage.gitignore_pattern_for("claude-md-ref", "gitignored") == ".claude/persona/"
    assert storage.gitignore_pattern_for("file", "gitignored") == ".profiles-assets/"
    assert storage.gitignore_pattern_for("claude-md", "gitignored") == ".profiles-assets/"


def test_ensure_gitignore_creates_file(tmp_path):
    changed = storage.ensure_gitignore(tmp_path)
    assert changed is True
    content = (tmp_path / ".gitignore").read_text()
    assert ".profiles-assets/" in content.splitlines()


def test_ensure_gitignore_idempotent(tmp_path):
    first = storage.ensure_gitignore(tmp_path)
    second = storage.ensure_gitignore(tmp_path)
    assert first is True
    assert second is False
    content = (tmp_path / ".gitignore").read_text()
    assert content.count(".profiles-assets/") == 1


def test_ensure_gitignore_appends_to_existing_file(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    changed = storage.ensure_gitignore(tmp_path)
    assert changed is True
    content = (tmp_path / ".gitignore").read_text()
    assert "node_modules/" in content
    assert ".profiles-assets/" in content.splitlines()


def test_write_markdown_output_file(tmp_path):
    path = storage.write_markdown_output(
        tmp_path, "file", "tracked", "ada", "# Ada\n"
    )
    assert path == str(tmp_path / "profiles" / "ada" / "ada.md")
    assert Path(path).read_text() == "# Ada\n"


def test_write_markdown_output_file_gitignored(tmp_path):
    path = storage.write_markdown_output(
        tmp_path, "file", "gitignored", "ada", "# Ada\n"
    )
    assert path == str(tmp_path / ".profiles-assets" / "ada" / "ada.md")
    assert Path(path).read_text() == "# Ada\n"


def test_claude_md_block_replace_in_place(tmp_path):
    block_v1 = "<!-- profile-gen:start slug=ada -->\nv1\n<!-- profile-gen:end slug=ada -->\n"
    block_v2 = "<!-- profile-gen:start slug=ada -->\nv2\n<!-- profile-gen:end slug=ada -->\n"

    path1 = storage.write_markdown_output(tmp_path, "claude-md", "tracked", "ada", block_v1)
    content1 = Path(path1).read_text()
    assert content1.count("<!-- profile-gen:start slug=ada -->") == 1
    assert "v1" in content1

    path2 = storage.write_markdown_output(tmp_path, "claude-md", "tracked", "ada", block_v2)
    content2 = Path(path2).read_text()
    assert content2.count("<!-- profile-gen:start slug=ada -->") == 1
    assert "v2" in content2
    assert "v1" not in content2


def test_claude_md_block_appended_alongside_other_content(tmp_path):
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# CLAUDE.md\n\nSome existing project notes.\n")

    block = "<!-- profile-gen:start slug=ada -->\nprofile\n<!-- profile-gen:end slug=ada -->\n"
    storage.write_markdown_output(tmp_path, "claude-md", "tracked", "ada", block)

    content = claude_md.read_text()
    assert "Some existing project notes." in content
    assert "<!-- profile-gen:start slug=ada -->" in content


def test_write_markdown_output_claude_md_ref_writes_standalone_file(tmp_path):
    path = storage.write_markdown_output(
        tmp_path, "claude-md-ref", "tracked", "ada", "# Ada\n"
    )
    assert path == str(tmp_path / "profiles" / "ada" / "ada.md")
    assert Path(path).read_text() == "# Ada\n"
    # write_markdown_output alone must NOT touch CLAUDE.md -- that's a separate call
    assert not (tmp_path / "CLAUDE.md").exists()


def test_write_markdown_output_claude_md_ref_gitignored_uses_fixed_private_path(tmp_path):
    path = storage.write_markdown_output(
        tmp_path, "claude-md-ref", "gitignored", "ada", "# Ada\n"
    )
    assert path == str(tmp_path / ".claude" / "persona" / "persona.md")
    assert Path(path).read_text() == "# Ada\n"
    assert "ada" not in Path(path).parts


def test_write_claude_md_reference_creates_relative_import(tmp_path):
    target = tmp_path / ".profiles-assets" / "ada" / "ada.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Ada\n")

    claude_md_path = storage.write_claude_md_reference(tmp_path, "ada", target)
    assert claude_md_path == str(tmp_path / "CLAUDE.md")

    content = (tmp_path / "CLAUDE.md").read_text()
    assert "<!-- profile-gen:start slug=ada -->" in content
    assert "@.profiles-assets/ada/ada.md" in content
    assert "<!-- profile-gen:end slug=ada -->" in content
    # the reference must not inline any actual persona content
    assert "# Ada" not in content


def test_write_claude_md_reference_replaces_in_place_on_regeneration(tmp_path):
    target = tmp_path / "profiles" / "ada" / "ada.md"
    target.parent.mkdir(parents=True)
    target.write_text("v1")
    storage.write_claude_md_reference(tmp_path, "ada", target)

    content1 = (tmp_path / "CLAUDE.md").read_text()
    assert content1.count("<!-- profile-gen:start slug=ada -->") == 1

    # regenerate at a different path (e.g. renamed) -- should replace, not duplicate
    new_target = tmp_path / "profiles" / "ada" / "ada-renamed.md"
    new_target.write_text("v2")
    storage.write_claude_md_reference(tmp_path, "ada", new_target)

    content2 = (tmp_path / "CLAUDE.md").read_text()
    assert content2.count("<!-- profile-gen:start slug=ada -->") == 1
    assert "@profiles/ada/ada-renamed.md" in content2
    assert "@profiles/ada/ada.md" not in content2


def test_write_claude_md_reference_preserves_existing_content_and_other_slugs(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# CLAUDE.md\n\nExisting project notes.\n")

    ada_target = tmp_path / "profiles" / "ada" / "ada.md"
    rho_target = tmp_path / "profiles" / "rho" / "rho.md"
    ada_target.parent.mkdir(parents=True)
    rho_target.parent.mkdir(parents=True)
    ada_target.write_text("ada")
    rho_target.write_text("rho")

    storage.write_claude_md_reference(tmp_path, "ada", ada_target)
    storage.write_claude_md_reference(tmp_path, "rho", rho_target)

    content = (tmp_path / "CLAUDE.md").read_text()
    assert "Existing project notes." in content
    assert "@profiles/ada/ada.md" in content
    assert "@profiles/rho/rho.md" in content


def test_claude_md_block_replace_preserves_other_slugs(tmp_path):
    block_ada = "<!-- profile-gen:start slug=ada -->\nada v1\n<!-- profile-gen:end slug=ada -->\n"
    block_rho = "<!-- profile-gen:start slug=rho -->\nrho v1\n<!-- profile-gen:end slug=rho -->\n"

    storage.write_markdown_output(tmp_path, "claude-md", "tracked", "ada", block_ada)
    storage.write_markdown_output(tmp_path, "claude-md", "tracked", "rho", block_rho)

    block_ada_v2 = "<!-- profile-gen:start slug=ada -->\nada v2\n<!-- profile-gen:end slug=ada -->\n"
    storage.write_markdown_output(tmp_path, "claude-md", "tracked", "ada", block_ada_v2)

    content = (tmp_path / "CLAUDE.md").read_text()
    assert content.count("slug=ada") == 2  # start + end marker
    assert content.count("slug=rho") == 2
    assert "ada v2" in content
    assert "ada v1" not in content
    assert "rho v1" in content
