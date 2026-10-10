import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import team_member  # noqa: E402


def _team(config_dir: Path, members: list) -> None:
    team = config_dir / "teams" / "session-1234abcd"
    team.mkdir(parents=True)
    (team / "config.json").write_text(json.dumps({"members": members}), encoding="utf-8")


def _start(agent_id: str, cwd: str = "/work/office") -> dict:
    return {"hook_event_name": "SubagentStart", "agent_id": agent_id, "cwd": cwd}


def test_in_process_member_gets_a_badge_beside_the_lead(tmp_path):
    _team(tmp_path, [{"agentId": "nora@session-1234abcd", "backendType": "in-process"}])

    assert team_member.plan(_start("nora@session-1234abcd"), config_dir=tmp_path) == [
        "--root", "/work/office", "--autostart-only", "--member", "nora",
    ]


def test_member_missing_from_config_is_treated_as_in_process(tmp_path):
    # in-process is the default mode; no config (or no entry yet) must not mean no badge
    assert team_member.plan(_start("nora@session-1234abcd"), config_dir=tmp_path)[-1] == "nora"


def test_split_pane_member_is_left_to_draw_its_own_badge(tmp_path):
    for backend in ("tmux", "iterm2"):
        config = tmp_path / backend
        _team(config, [{"agentId": "sol@session-1234abcd", "backendType": backend}])
        assert team_member.plan(_start("sol@session-1234abcd"), config_dir=config) == []


def test_stop_removes_only_that_members_badge(tmp_path):
    payload = {"hook_event_name": "SubagentStop", "agent_id": "nora@session-1234abcd"}
    assert team_member.plan(payload, config_dir=tmp_path) == ["--clear", "--member", "nora"]


def test_plain_subagents_and_bad_payloads_do_nothing(tmp_path):
    assert team_member.plan(_start("a33d61a10959f1b10"), config_dir=tmp_path) == []
    assert team_member.plan({}, config_dir=tmp_path) == []
    assert team_member.plan(_start("@session-1234abcd"), config_dir=tmp_path) == []
    other = {"hook_event_name": "PreToolUse", "agent_id": "nora@session-1234abcd"}
    assert team_member.plan(other, config_dir=tmp_path) == []


def test_falls_back_to_the_project_dir_without_a_cwd(tmp_path):
    payload = {"hook_event_name": "SubagentStart", "agent_id": "nora@session-1234abcd"}
    assert team_member.plan(payload, "/work/office", config_dir=tmp_path)[:2] == ["--root", "/work/office"]
