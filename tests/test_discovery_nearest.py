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


def _work_tree(tmp_path: Path) -> Path:
    evidence = tmp_path / "Work"
    _project(evidence, "Evie Marsh", "evidence")
    _project(evidence / "clients" / "Beacon", "Cora Beacon", "beacon")
    acme = evidence / "clients" / "Acme"
    acme.mkdir(parents=True)
    (acme / "CLAUDE.md").write_text("# Acme\n\nClient notes, no persona.\n", encoding="utf-8")
    return evidence


def _names(start: Path) -> list[str]:
    return [p.fields["name"] for p in discovery.discover_for_session(start, agent_name="")]


def test_subdirectory_without_claude_md_keeps_the_parents_persona(tmp_path):
    evidence = _work_tree(tmp_path)

    assert _names(evidence / "clients") == ["Evie Marsh"]


def test_subdirectory_with_its_own_persona_shows_that_one(tmp_path):
    evidence = _work_tree(tmp_path)

    assert _names(evidence / "clients" / "Beacon") == ["Cora Beacon"]


def test_claude_md_without_a_persona_does_not_hide_the_parents(tmp_path):
    evidence = _work_tree(tmp_path)

    assert _names(evidence / "clients" / "Acme") == ["Evie Marsh"]


def test_inherited_persona_resolves_against_the_directory_that_declared_it(tmp_path):
    evidence = _work_tree(tmp_path)

    [persona] = discovery.discover_for_session(evidence / "clients" / "Acme", agent_name="")

    assert persona.root == evidence.resolve()
    assert persona.markdown_path == evidence / ".claude" / "persona" / "persona.md"


def test_relative_start_is_walked_up_too(tmp_path, monkeypatch):
    evidence = _work_tree(tmp_path)
    monkeypatch.chdir(evidence / "clients")

    assert _names(Path(".")) == ["Evie Marsh"]


def test_team_member_persona_is_found_from_a_subdirectory(tmp_path):
    evidence = _work_tree(tmp_path)
    member = evidence / ".profiles-assets" / "nadia" / "nadia.md"
    member.parent.mkdir(parents=True)
    member.write_text('---\nschema_version: 1\nname: "Nadia Okafor"\nslug: "nadia"\n---\n', encoding="utf-8")

    personas = discovery.discover_for_session(evidence / "clients" / "Acme", agent_name="nadia")

    assert [p.fields["name"] for p in personas] == ["Nadia Okafor"]
    assert personas[0].root == evidence.resolve()


def _cases_tree(tmp_path: Path) -> Path:
    # A lead project whose sub-projects each carry their own persona, as a team works across.
    office = tmp_path / "Office"
    _project(office, "Lead Lyra", "lead")
    _project(office / "matters" / "North", "Nora Vale", "persona")
    _project(office / "matters" / "South", "Sol Brandt", "persona")
    (office / "matters" / "North" / "notes" / "deep").mkdir(parents=True)
    return office


def test_team_member_finds_its_persona_in_a_sibling_project(tmp_path):
    # Spawned from inside North's tree, but named for South's persona.
    office = _cases_tree(tmp_path)
    start = office / "matters" / "North" / "notes" / "deep"

    found = discovery.discover_for_session(start, agent_name="sol")
    assert [p.fields["name"] for p in found] == ["Sol Brandt"]
    assert found[0].root == office / "matters" / "South"


def test_team_member_name_matches_first_name_full_slug_or_slug_field(tmp_path):
    office = _cases_tree(tmp_path)
    start = office / "matters" / "North"

    for name in ("nora", "Nora", "nora-vale"):
        assert _names_for(start, name) == ["Nora Vale"]
    assert _names_for(start, "lead") == ["Lead Lyra"]


def test_nearest_match_wins(tmp_path):
    office = _cases_tree(tmp_path)
    _project(office / "matters" / "North" / "notes", "Nora Quill", "persona")

    assert _names_for(office / "matters" / "North" / "notes" / "deep", "nora") == ["Nora Quill"]


def test_team_member_with_no_matching_persona_still_gets_none(tmp_path):
    office = _cases_tree(tmp_path)

    assert _names_for(office / "matters" / "North", "zed") == []


def _names_for(start: Path, agent_name: str) -> list[str]:
    return [p.fields["name"] for p in discovery.discover_for_session(start, agent_name=agent_name)]
