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

Claude Code *merges* hook definitions from every settings file that applies to a session rather
than letting the nearest one win, so a project nested under another project that also registers
this hook fires it twice and the intro is printed twice. `_claim_intro()` makes the script
idempotent per session: the first invocation for a given `session_id` claims it (via an flock'd
claim file under ~/.cache/profile-gen/session-intro) and any other invocation arriving within
DEDUPE_WINDOW_SECONDS emits nothing. The window, rather than a permanent claim, is what keeps a
later legitimate re-fire of the same session id working -- `/clear` re-runs SessionStart, and
whether it also mints a new session id is a harness detail this script shouldn't depend on.

Never errors out over a missing persona, a non-git ROOT, or any other lookup failure -- worst
case it emits nothing rather than blocking the session from starting.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import discovery  # noqa: E402

FILE_COUNT = 8
DEDUPE_DIR = Path.home() / ".cache" / "profile-gen" / "session-intro"
DEDUPE_WINDOW_SECONDS = 30.0
CLAIM_TTL_SECONDS = 86400.0
SKIP_DIR_NAMES = {"node_modules", "__pycache__", "dist", "build", "venv", "env"}
WALK_TIME_BUDGET_SECONDS = 1.5


def _read_hook_payload() -> dict:
    """The JSON hook input Claude Code writes on stdin, or {} when there isn't any.

    Skipped entirely when stdin is a terminal, so running this script by hand doesn't hang
    waiting on input that will never arrive."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _prune_claims(now: float) -> None:
    try:
        for claim in DEDUPE_DIR.glob("*.claim"):
            try:
                if now - claim.stat().st_mtime > CLAIM_TTL_SECONDS:
                    claim.unlink()
            except OSError:
                continue
    except OSError:
        return


def _claim_intro(session_id: str | None, now: float | None = None) -> bool:
    """Whether *this* invocation should emit the intro for `session_id`.

    True for the first caller in a session and False for anyone arriving within
    DEDUPE_WINDOW_SECONDS after it -- which is what stops a hook registered in both a project's
    and an ancestor project's settings.json from introducing the persona twice. The claim is
    keyed on session_id alone, not on --root, because the duplicate invocations may well pass
    different roots (a nested project's settings file can hardcode its own).

    Any failure to take the claim (no session_id, unwritable cache dir, no flock) returns True:
    a duplicated intro is cosmetic, a missing one is the feature not working.
    """
    if not session_id:
        return True
    now = time.time() if now is None else now
    key = hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()[:32]
    try:
        DEDUPE_DIR.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(DEDUPE_DIR / f"{key}.claim"), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return True
    try:
        if fcntl is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
            except OSError:
                pass
        try:
            claimed_at = float(os.read(fd, 64).decode("utf-8", "replace").strip() or 0)
        except (OSError, ValueError):
            claimed_at = 0.0
        if 0 <= now - claimed_at < DEDUPE_WINDOW_SECONDS:
            return False
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, repr(now).encode("utf-8"))
        except OSError:
            return True
        return True
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


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

    payload = _read_hook_payload()
    now = time.time()
    if not _claim_intro(payload.get("session_id"), now):
        return 0
    _prune_claims(now)

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
