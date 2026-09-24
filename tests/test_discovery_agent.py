import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen import discovery  # noqa: E402

LEAD_REF = """<!-- profile-gen:start slug=lead -->
@.claude/persona/persona.md
<!-- profile-gen:end slug=lead -->
"""


def _persona(path: Path, name: str, slug: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'---\nschema_version: 1\nname: "{name}"\nslug: "{slug}"\n'
        f'image: "{path.parent.name}/{slug}.png"\n---\n\n# {name}\n',
        encoding="utf-8",
    )


def _project_with_lead(root: Path) -> None:
    (root / "CLAUDE.md").write_text(LEAD_REF, encoding="utf-8")
    _persona(root / ".claude" / "persona" / "persona.md", "Jennifer Voss", "lead")


def test_agent_name_from_args_takes_nearest_ancestor():
    lines = [
        "/bin/sh -c python3 show_profile.py",
        "/x/claude --agent-id nadia@team --agent-name nadia-okafor --team-name team",
        "/x/claude --agent-name someone-else",
    ]
    assert discovery.agent_name_from_args(lines) == "nadia-okafor"


def test_agent_name_from_args_accepts_equals_form_and_rejects_dot_names():
    assert discovery.agent_name_from_args(["claude --agent-name=felix"]) == "felix"
    assert discovery.agent_name_from_args(["claude --agent-name .."]) is None
    assert discovery.agent_name_from_args(["claude --resume abc", "zsh"]) is None


def test_agent_name_cannot_walk_out_of_profiles():
    # The pattern stops at the first character that isn't a name character, so a path separator
    # never reaches profiles/<name>/.
    assert discovery.agent_name_from_args(["claude --agent-name ../../etc"]) is None


def test_team_member_gets_its_own_persona_not_the_leads(tmp_path):
    _project_with_lead(tmp_path)
    _persona(tmp_path / ".profiles-assets" / "nadia-okafor" / "nadia-okafor.md", "Nadia Okafor", "nadia-okafor")

    personas = discovery.discover_for_session(tmp_path, agent_name="nadia-okafor")

    assert [p.fields["name"] for p in personas] == ["Nadia Okafor"]
    assert personas[0].markdown_path.name == "nadia-okafor.md"


def test_tracked_profiles_dir_is_found_too(tmp_path):
    _project_with_lead(tmp_path)
    _persona(tmp_path / "profiles" / "felix" / "felix.md", "Felix Marchetti", "felix")

    personas = discovery.discover_for_session(tmp_path, agent_name="felix")

    assert [p.fields["name"] for p in personas] == ["Felix Marchetti"]


def test_team_member_without_a_persona_gets_nothing_rather_than_the_lead(tmp_path):
    _project_with_lead(tmp_path)

    assert discovery.discover_for_session(tmp_path, agent_name="rowan") == []


def test_ordinary_session_still_gets_the_project_persona(tmp_path):
    _project_with_lead(tmp_path)

    personas = discovery.discover_for_session(tmp_path, agent_name="")

    assert [p.fields["name"] for p in personas] == ["Jennifer Voss"]


def test_env_override_names_the_agent(tmp_path, monkeypatch):
    _project_with_lead(tmp_path)
    _persona(tmp_path / ".profiles-assets" / "ines" / "ines.md", "Ines Carvalho", "ines")
    monkeypatch.setenv(discovery.AGENT_NAME_ENV, "ines")

    assert [p.fields["name"] for p in discovery.discover_for_session(tmp_path)] == ["Ines Carvalho"]

    monkeypatch.setenv(discovery.AGENT_NAME_ENV, "")
    assert [p.fields["name"] for p in discovery.discover_for_session(tmp_path)] == ["Jennifer Voss"]


def test_current_agent_name_reads_the_process_table(monkeypatch):
    monkeypatch.delenv(discovery.AGENT_NAME_ENV, raising=False)
    monkeypatch.setattr(discovery.sys, "platform", "darwin")
    monkeypatch.setattr(
        discovery, "_ancestor_args_posix",
        lambda pid: ["/bin/sh -c hook", "/x/claude --agent-name rowan-achterberg --team-name t"],
    )
    assert discovery.current_agent_name() == "rowan-achterberg"
