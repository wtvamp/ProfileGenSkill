#!/usr/bin/env python3
"""SessionStart hook: gather persona + recent-activity context for a self-introduction.

Prints nothing about the model's identity itself -- it collects two things a SessionStart hook
can see that the model can't derive from the conversation alone, and hands them back as
`hookSpecificOutput.additionalContext` so Claude can introduce itself at the top of the session:

  1. The active persona (if any) discovered via `<ROOT>/CLAUDE.md`'s profile-gen marker blocks --
     name and the free-text `## Personality` section from its markdown file.
  2. A short recent-activity summary from `git log` in ROOT, so the intro reflects what was
     actually worked on lately instead of a generic greeting.

Never errors out over a missing persona, a non-git ROOT, or any other lookup failure -- worst
case it emits an empty/minimal additionalContext rather than blocking the session from starting.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import discovery  # noqa: E402


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


def _recent_activity(root: Path, count: int = 8) -> str | None:
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


def build_context(root: Path) -> str | None:
    personas = discovery.discover_personas(root)
    activity = _recent_activity(root)

    parts = []
    if personas:
        persona = personas[0]
        name = persona.fields.get("name") or persona.slug
        personality = _personality_section(persona.markdown_path)
        persona_bit = f"Your persona for this project is {name}."
        if personality:
            persona_bit += f" Personality: {personality}"
        parts.append(persona_bit)

    if activity:
        parts.append(
            "Recent commits in this repo (most recent first, for context only -- "
            "don't just paste this list):\n" + activity
        )

    if not parts:
        return None

    parts.append(
        "At the very start of your first reply this session, before addressing anything else "
        "the user asks, briefly introduce yourself in character: who you are, what you do in "
        "this project, and a one- or two-sentence summary of what's been worked on lately based "
        "on the commits above. Keep it short -- a few sentences, not a report -- then proceed "
        "with the user's actual request."
    )
    return "\n\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="project root to inspect")
    args = parser.parse_args()

    root = Path(args.root)
    context = build_context(root)
    if context:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
