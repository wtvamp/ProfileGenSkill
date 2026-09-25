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
