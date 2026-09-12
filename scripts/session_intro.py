#!/usr/bin/env python3
"""SessionStart hook: gather persona + recent-activity context for a self-introduction.

It collects two things a SessionStart hook can see that the model can't derive from the
conversation alone:

  1. The active persona (if any) discovered via `<ROOT>/CLAUDE.md`'s profile-gen marker blocks --
     name and the free-text `## Personality` section from its markdown file.
  2. A short recent-activity summary, so the intro reflects what was actually worked on lately
     instead of a generic greeting.

Recent activity is the most-recently-modified files under ROOT (by mtime) -- an observed-live
persona once stated a "most recently" narrative pulled from the auto-memory index (MEMORY.md) as
settled fact, and it was stale: memory is written once and organized by topic, not chronology (see
the memory system's own guidance), so it can describe something worked on weeks ago as if it were
current. File mtimes can't be stale in that way -- they're read fresh every time this hook runs.
`git log` is a fallback only, for a project where the most-recently-touched files aren't a useful
signal (e.g. mid-clone, or nothing has been touched since checkout).

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
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import discovery  # noqa: E402

FILE_COUNT = 8
SKIP_DIR_NAMES = {"node_modules", "__pycache__", "dist", "build", "venv", "env"}
WALK_TIME_BUDGET_SECONDS = 1.5


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


def _recent_files_activity(root: Path, count: int = FILE_COUNT) -> str | None:
    """The `count` most-recently-modified files under root, "YYYY-MM-DD  relative/path" per line,
    newest first. Skips hidden dirs/files (.git, .claude, ...) and common noise directories.
    Bounded by a wall-clock budget rather than a file-count cap, so a huge tree degrades to a
    partial-but-fast answer instead of a slow one."""
    deadline = time.monotonic() + WALK_TIME_BUDGET_SECONDS
    candidates: list[tuple[float, Path]] = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIR_NAMES]
            for filename in filenames:
                if filename.startswith("."):
                    continue
                path = Path(dirpath) / filename
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                candidates.append((mtime, path))
            if time.monotonic() >= deadline:
                break
    except OSError:
        return None

    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0], reverse=True)

    lines = []
    for mtime, path in candidates[:count]:
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
        date = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        lines.append(f"{date}  {rel}")
    return "\n".join(lines)


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
    files = _recent_files_activity(root)
    if files:
        return files, "files"
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
        if source == "files":
            label = (
                "Files most recently touched in this project, newest first (this tells you "
                "*what* changed last, not *what changed about it* -- don't invent details about "
                "what was done, and don't state this as a settled narrative; for context only, "
                "don't just paste this list):\n"
            )
        else:
            label = (
                "Recent commits in this repo -- no useful file-recency signal was available, so "
                "this is a fallback only (most recent first, for context only -- don't just paste "
                "this list):\n"
            )
        parts.append(label + activity)

    if not parts:
        return None

    parts.append(
        "At the very start of your first reply this session, before addressing anything else "
        "the user asks, briefly introduce yourself in character: who you are, what you do in "
        "this project, and -- only if you can say something concrete and accurate from the "
        "activity above -- a one-sentence gesture at what's recently been touched. If you're not "
        "sure what a file was for, don't guess at a narrative; a short, honest intro beats a "
        "confident wrong one. Keep it short -- a few sentences, not a report -- then proceed with "
        "the user's actual request."
    )
    return "\n\n".join(parts)


def _first_activity_teaser(activity: str, source: str) -> str | None:
    first = activity.splitlines()[0]
    if source == "files":
        # "2026-09-12  path/to/file.md" -> "path/to/file.md"
        parts = first.split(None, 1)
        return parts[1] if len(parts) == 2 else None
    # git log line: "2026-09-12 Subject text"
    parts = first.split(" ", 1)
    return parts[1] if len(parts) == 2 else None


def build_system_message(name: str | None, activity: str | None, source: str) -> str | None:
    if not name and not activity:
        return None
    greeting = f"👋 {name}" if name else "👋"
    latest = _first_activity_teaser(activity, source) if activity else None
    if latest:
        if source == "files":
            greeting += f" here. Most recently touched: {latest}."
        else:
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
