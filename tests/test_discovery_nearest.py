import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen import discovery  # noqa: E402


def _ref(slug: str) -> str:
    return (
        f"<!-- profile-gen:start slug={slug} -->\n"
        f"@.claude/persona/persona.md\n"
        f"<!-- profile-gen:end slug={slug} -->\n"
    )


def _project(root: Path, name: str, slug: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "CLAUDE.md").write_text(_ref(slug), encoding="utf-8")
    persona = root / ".claude" / "persona" / "persona.md"
    persona.parent.mkdir(parents=True, exist_ok=True)
    persona.write_text(
        f'---\nschema_version: 1\nname: "{name}"\nslug: "{slug}"\n'
        f'image: ".claude/persona/persona.png"\n---\n\n# {name}\n',
        encoding="utf-8",
    )


def _evidence_tree(tmp_path: Path) -> Path:
    evidence = tmp_path / "Evidence"
    _project(evidence, "Evie Marsh", "evidence")
    _project(evidence / "01_CASES" / "Caldwell", "Cora Caldwell", "caldwell")
    adoreal = evidence / "01_CASES" / "Adoreal"
    adoreal.mkdir(parents=True)
    (adoreal / "CLAUDE.md").write_text("# Adoreal\n\nCase notes, no persona.\n", encoding="utf-8")
    return evidence


def _names(start: Path) -> list[str]:
    return [p.fields["name"] for p in discovery.discover_for_session(start, agent_name="")]


def test_subdirectory_without_claude_md_keeps_the_parents_persona(tmp_path):
    evidence = _evidence_tree(tmp_path)

    assert _names(evidence / "01_CASES") == ["Evie Marsh"]


def test_subdirectory_with_its_own_persona_shows_that_one(tmp_path):
    evidence = _evidence_tree(tmp_path)

    assert _names(evidence / "01_CASES" / "Caldwell") == ["Cora Caldwell"]


def test_claude_md_without_a_persona_does_not_hide_the_parents(tmp_path):
    evidence = _evidence_tree(tmp_path)

    assert _names(evidence / "01_CASES" / "Adoreal") == ["Evie Marsh"]


def test_inherited_persona_resolves_against_the_directory_that_declared_it(tmp_path):
    evidence = _evidence_tree(tmp_path)

    [persona] = discovery.discover_for_session(evidence / "01_CASES" / "Adoreal", agent_name="")

    assert persona.root == evidence.resolve()
    assert persona.markdown_path == evidence / ".claude" / "persona" / "persona.md"


def test_relative_start_is_walked_up_too(tmp_path, monkeypatch):
    evidence = _evidence_tree(tmp_path)
    monkeypatch.chdir(evidence / "01_CASES")

    assert _names(Path(".")) == ["Evie Marsh"]


def test_team_member_persona_is_found_from_a_subdirectory(tmp_path):
    evidence = _evidence_tree(tmp_path)
    member = evidence / ".profiles-assets" / "nadia" / "nadia.md"
    member.parent.mkdir(parents=True)
    member.write_text('---\nschema_version: 1\nname: "Nadia Okafor"\nslug: "nadia"\n---\n', encoding="utf-8")

    personas = discovery.discover_for_session(evidence / "01_CASES" / "Adoreal", agent_name="nadia")

    assert [p.fields["name"] for p in personas] == ["Nadia Okafor"]
    assert personas[0].root == evidence.resolve()
