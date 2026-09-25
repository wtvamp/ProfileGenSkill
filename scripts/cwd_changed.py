#!/usr/bin/env python3
"""CwdChanged hook: swap the on-screen persona when the session moves into another persona's tree.

Claude Code fires `CwdChanged` with `{"old_cwd", "new_cwd"}` on stdin whenever the session's
working directory changes (an agent `cd`-ing in its shell tool). The persona for a directory is the
nearest CLAUDE.md at or above it that declares one (see profilegen/discovery.py), so most moves --
`Evidence` -> `Evidence/01_CASES` -- land on the same persona and nothing is redrawn. Only when the
nearest persona actually differs (`01_CASES` -> `01_CASES/Caldwell`, or back out again) is the badge
replaced:

- the new persona is drawn the way the SessionStart hook draws one (`--autostart-only`), after
  clearing the old one -- so a new persona whose `display.autostart` is false, or whose image and
  name are both off, leaves no badge rather than the previous persona's face;
- a directory with no persona anywhere above it changes nothing, since the session still has the
  CLAUDE.md it started with loaded;
- a directory outside the session's project (`$CLAUDE_PROJECT_DIR`) counts as the project itself.
  Claude Code snaps the shell back to the project after any command that `cd`s out of it, and that
  reset fires no CwdChanged -- so taking `cd ~`'s persona (`~/CLAUDE.md`'s, usually) would leave it
  stuck on screen after the session was already back home.

Wire it in beside the SessionStart hook:

  "CwdChanged": [{"hooks": [{"type": "command", "async": true, "timeout": 60,
    "command": "python3 <SKILL_DIR>/scripts/cwd_changed.py >/dev/null 2>&1 || true"}]}]

Never fails the hook: bad input or a display error exits 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import discovery  # noqa: E402

SHOW_PROFILE = Path(__file__).resolve().parent / "show_profile.py"


def _read_payload() -> dict:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _identity(personas: list[discovery.DiscoveredPersona]) -> list[tuple[str, str]]:
    return [(str(p.markdown_path), p.slug) for p in personas]


def _within_project(cwd: str, project_dir: str | None) -> str:
    """`cwd`, or the project itself when `cwd` is outside it (see the module docstring)."""
    if not project_dir:
        return cwd
    project = Path(project_dir).resolve()
    here = Path(cwd).resolve()
    return cwd if here == project or project in here.parents else str(project)


def plan(old_cwd: str | None, new_cwd: str | None, project_dir: str | None = None) -> list[list[str]]:
    """The show_profile.py argument lists to run for this move, in order -- empty for no change."""
    if not new_cwd:
        return []
    new_cwd = _within_project(new_cwd, project_dir)
    new = discovery.discover_for_session(Path(new_cwd))
    if not new:
        return []
    old = discovery.discover_for_session(Path(_within_project(old_cwd, project_dir))) if old_cwd else []
    if _identity(new) == _identity(old):
        return []
    return [["--clear"], ["--root", new_cwd, "--autostart-only"]]


def main() -> int:
    payload = _read_payload()
    try:
        steps = plan(payload.get("old_cwd"), payload.get("new_cwd"), os.environ.get("CLAUDE_PROJECT_DIR"))
    except Exception:
        return 0
    for step in steps:
        try:
            subprocess.run(
                [sys.executable, str(SHOW_PROFILE), *step],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
