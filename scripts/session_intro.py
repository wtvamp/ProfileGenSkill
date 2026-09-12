#!/usr/bin/env python3
"""SessionStart hook: gather persona + recent-activity context for a self-introduction.

It collects two things a SessionStart hook can see that the model can't derive from the
conversation alone:

  1. The active persona (if any) discovered via `<ROOT>/CLAUDE.md`'s profile-gen marker blocks --
     name and the free-text `## Personality` section from its markdown file.
  2. A short recent-activity summary, so the intro reflects what was actually worked on lately
     instead of a generic greeting. This is drawn from Claude Code's own auto-memory index for
     this project (`MEMORY.md` under `~/.claude/projects/<sanitized-root>/memory/`) when one
     exists -- it's built from actual past sessions with the user, which is what "what have you
     been working on" should mean, not commit messages. `git log` is only a fallback for a
     project with no accumulated memory yet.

These are handed back two ways:

  - `hookSpecificOutput.additionalContext` -- primes Claude to open its first reply this session
    with a fuller in-character introduction. Only appears once the user sends a message, since a
    hook can't make the model speak on its own.
  - `systemMessage` -- a short static one-liner the harness displays immediately at session
    start, with no user input needed, so there's some visible greeting even before the user types
    anything.

Never errors out over a missing persona, a non-git ROOT, or any other lookup failure -- worst
case it emits nothing rather than blocking the session from starting.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import discovery  # noqa: E402

MEMORY_LINE_LIMIT = 12


def _personality_section(markdown_path: Path) -> str | None:
    try:
        text = markdown_path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower() == "## personality":
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for i in range(start, len(lines)):
        if lines[i].startswith("#"):
            end = i
            break
    section = "\n".join(lines[start:end]).strip()
    return section or None


def _sanitized_project_key(root: Path) -> str:
    """Mirrors Claude Code's own cwd -> ~/.claude/projects/<key> mangling: every non-alnum
    character (path separators, underscores, spaces, ...) becomes a hyphen."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(root.resolve()))


def _memory_activity(root: Path) -> str | None:
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")).expanduser()
    memory_index = config_dir / "projects" / _sanitized_project_key(root) / "memory" / "MEMORY.md"
    try:
        text = memory_index.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    return "\n".join(lines[:MEMORY_LINE_LIMIT])


def _git_activity(root: Path, count: int = 8) -> str | None:
    try:
        result = subprocess.run(
            ["git", "log", f"-{count}", "--date=short", "--pretty=format:%ad %s"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _recent_activity(root: Path) -> tuple[str | None, str]:
    """Prefers real session/conversation history (the auto-memory index) over git log, since
    that's what "what have you worked on lately" should reflect. Returns (text, source)."""
    memory = _memory_activity(root)
    if memory:
        return memory, "memory"
    git = _git_activity(root)
    if git:
        return git, "git"
    return None, "none"


def build_context(name: str | None, personality: str | None, activity: str | None, source: str) -> str | None:
    parts = []
    if name:
        persona_bit = f"Your persona for this project is {name}."
        if personality:
            persona_bit += f" Personality: {personality}"
        parts.append(persona_bit)

    if activity:
        if source == "memory":
            label = (
                "Recent notes from your own memory of past sessions on this project (most "
                "recent first, for context only -- don't just paste this list):\n"
            )
        else:
            label = (
                "Recent commits in this repo -- no session memory exists yet for this project, "
                "so this is a fallback signal only (most recent first, for context only -- "
                "don't just paste this list):\n"
            )
        parts.append(label + activity)

    if not parts:
        return None

    parts.append(
        "At the very start of your first reply this session, before addressing anything else "
        "the user asks, briefly introduce yourself in character: who you are, what you do in "
        "this project, and a one- or two-sentence summary of what's been worked on lately based "
        "on the notes above. Keep it short -- a few sentences, not a report -- then proceed "
        "with the user's actual request."
    )
    return "\n\n".join(parts)


def _first_activity_teaser(activity: str, source: str) -> str | None:
    first = activity.splitlines()[0]
    if source == "memory":
        # "- [Title](file.md) — detail" -> "Title"
        first = re.sub(r"^-\s*", "", first)
        first = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", first)
        return first.split(" — ", 1)[0].strip() or None
    # git log line: "2026-09-12 Subject text"
    parts = first.split(" ", 1)
    return parts[1] if len(parts) == 2 else None


def build_system_message(name: str | None, activity: str | None, source: str) -> str | None:
    if not name and not activity:
        return None
    greeting = f"👋 {name}" if name else "👋"
    latest = _first_activity_teaser(activity, source) if activity else None
    if latest:
        greeting += f" here. Lately: {latest}."
    else:
        greeting += " here."
    return greeting


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="project root to inspect")
    args = parser.parse_args()

    root = Path(args.root)
    personas = discovery.discover_personas(root)
    activity, source = _recent_activity(root)

    name = None
    personality = None
    if personas:
        persona = personas[0]
        name = persona.fields.get("name") or persona.slug
        personality = _personality_section(persona.markdown_path)

    context = build_context(name, personality, activity, source)
    system_message = build_system_message(name, activity, source)

    output = {}
    if context:
        output["hookSpecificOutput"] = {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    if system_message:
        output["systemMessage"] = system_message
    if output:
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
