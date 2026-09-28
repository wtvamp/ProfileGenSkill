import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import cwd_changed  # noqa: E402
from profilegen import discovery  # noqa: E402
from test_discovery_nearest import _work_tree  # noqa: E402


@pytest.fixture(autouse=True)
def _ordinary_session(monkeypatch):
    monkeypatch.setenv(discovery.AGENT_NAME_ENV, "")


def test_moving_within_one_personas_tree_redraws_nothing(tmp_path):
    evidence = _work_tree(tmp_path)

    assert cwd_changed.plan(str(evidence), str(evidence / "clients")) == []
    assert cwd_changed.plan(str(evidence / "clients"), str(evidence / "clients" / "Acme")) == []


def test_moving_into_a_subdirectory_with_its_own_persona_swaps_the_badge(tmp_path):
    evidence = _work_tree(tmp_path)
    beacon = evidence / "clients" / "Beacon"

    assert cwd_changed.plan(str(evidence / "clients"), str(beacon)) == [
        ["--clear"], ["--root", str(beacon), "--autostart-only"],
    ]


def test_moving_back_out_restores_the_parents_persona(tmp_path):
    evidence = _work_tree(tmp_path)
    cases = evidence / "clients"

    assert cwd_changed.plan(str(cases / "Beacon"), str(cases))[-1] == ["--root", str(cases), "--autostart-only"]


def test_moving_somewhere_with_no_persona_leaves_the_badge_alone(tmp_path):
    evidence = _work_tree(tmp_path)
    elsewhere = tmp_path / "scratch"
    elsewhere.mkdir()

    assert cwd_changed.plan(str(evidence), str(elsewhere)) == []


def test_missing_payload_fields_do_nothing(tmp_path):
    assert cwd_changed.plan(None, None) == []
    assert cwd_changed.plan(str(tmp_path), None) == []


def _home_with_persona(tmp_path: Path) -> Path:
    # ~/CLAUDE.md declaring a persona of its own, as on a setup with a home-level default persona (Juniper).
    from test_discovery_nearest import _project
    _project(tmp_path, "Juniper", "persona")
    return tmp_path


def test_cd_out_of_the_project_does_not_take_the_home_persona(tmp_path):
    home = _home_with_persona(tmp_path)
    repo = home / "Source" / "other-repo"
    from test_discovery_nearest import _project
    _project(repo, "Nora Vale", "nora-vale")

    # `cd ~` inside a Bash call: Claude Code resets the shell to the repo afterwards without firing
    # CwdChanged, so drawing Juniper here would leave her stuck on screen.
    assert cwd_changed.plan(str(repo), str(home), project_dir=str(repo)) == []
    assert cwd_changed.plan(str(repo), str(home / "tmp"), project_dir=str(repo)) == []


def test_coming_back_into_the_project_from_outside_is_not_a_persona_change(tmp_path):
    home = _home_with_persona(tmp_path)
    repo = home / "Source" / "other-repo"
    from test_discovery_nearest import _project
    _project(repo, "Nora Vale", "nora-vale")

    # The outside directory already counted as the project, so returning is no change at all.
    assert cwd_changed.plan(str(home), str(repo), project_dir=str(repo)) == []


def test_moves_inside_the_project_still_swap(tmp_path):
    evidence = _work_tree(tmp_path)
    beacon = evidence / "clients" / "Beacon"

    assert cwd_changed.plan(str(evidence), str(beacon), project_dir=str(evidence))[-1] == [
        "--root", str(beacon), "--autostart-only",
    ]
    # Leaving the project from inside Beacon goes back to the project's persona.
    assert cwd_changed.plan(str(beacon), str(tmp_path / "elsewhere"), project_dir=str(evidence))[-1] == [
        "--root", str(evidence.resolve()), "--autostart-only",
    ]
