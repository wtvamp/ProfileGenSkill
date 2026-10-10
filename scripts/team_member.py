#!/usr/bin/env python3
"""SubagentStart/SubagentStop hook: give each agent-team member its own badge while it works.

An agent-team member is spawned with an id of the form `<name>@<team>` (a plain subagent's id has
no `@`, and a plain subagent is not a persona, so it gets nothing). Claude Code fires
`SubagentStart` when a member starts and `SubagentStop` when it finishes, with `agent_id` in the
payload either way -- whatever display mode the team runs in, tmux or not.

- An **in-process** member (the default mode, and the only one without tmux or iTerm2 split
  panes) shares the lead's process and terminal, so the lead draws it: its persona -- found by
  name, see discovery.discover_for_session() -- as an extra badge beside the lead's own, removed
  again when the member stops (or when the lead's session exits).
- A **split-pane** member is a process of its own in a pane of its own, and its own SessionStart
  hook already draws its badge there. The lead leaves it alone rather than draw it twice; the
  team's config (`<config dir>/teams/<team>/config.json`) says which kind each member is.

Wire it in beside the SessionStart hook:

  "SubagentStart": [{"hooks": [{"type": "command", "async": true, "timeout": 60,
    "command": "python3 <SKILL_DIR>/scripts/team_member.py >/dev/null 2>&1 || true"}]}],
  "SubagentStop": [{"hooks": [{"type": "command", "async": true, "timeout": 60,
    "command": "python3 <SKILL_DIR>/scripts/team_member.py >/dev/null 2>&1 || true"}]}]

Never fails the hook: bad input or a display error exits 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SHOW_PROFILE = Path(__file__).resolve().parent / "show_profile.py"


def _read_payload() -> dict:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _config_dir() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(configured).expanduser() if configured else Path.home() / ".claude"


def _runs_in_its_own_pane(agent_id: str, team: str, config_dir: Path) -> bool:
    """True when the team's config says this member is not in-process. Unreadable config -> False,
    since in-process is the default mode and drawing a badge beats silently drawing none."""
    try:
        config = json.loads((config_dir / "teams" / team / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    for member in config.get("members") or []:
        if isinstance(member, dict) and member.get("agentId") == agent_id:
            backend = member.get("backendType")
            return bool(backend) and backend != "in-process"
    return False


def plan(payload: dict, project_dir: str | None = None, config_dir: Path | None = None) -> list[str]:
    """The show_profile.py arguments to run for this event -- empty for nothing to do."""
    agent_id = str(payload.get("agent_id") or "")
    name, sep, team = agent_id.partition("@")
    if not sep or not name or not team:
        return []
    event = payload.get("hook_event_name")
    if event == "SubagentStop":
        return ["--clear", "--member", name]
    if event != "SubagentStart":
        return []
    if _runs_in_its_own_pane(agent_id, team, config_dir or _config_dir()):
        return []
    root = payload.get("cwd") or project_dir or os.getcwd()
    return ["--root", str(root), "--autostart-only", "--member", name]


def main() -> int:
    payload = _read_payload()
    try:
        steps = plan(payload, os.environ.get("CLAUDE_PROJECT_DIR"))
        if steps:
            subprocess.run(
                [sys.executable, str(SHOW_PROFILE), *steps],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=50,
            )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
