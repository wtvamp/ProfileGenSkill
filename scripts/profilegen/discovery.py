"""Shared persona discovery for show_profile.py / toggle_display.py.

Finds every persona currently auto-loaded via a project's CLAUDE.md profile-gen marker blocks,
alongside the actual markdown file each one's content (and thus its `display:` block) lives in --
a standalone `persona.md`/`profiles/<slug>/<slug>.md` for `claude-md-ref`, or CLAUDE.md itself for
a fully-embedded (`claude-md`) persona. `embedded=True` on the latter tells a caller that wants to
edit the `display:` block that it must confine the edit to that persona's own marker-delimited
region within CLAUDE.md (see `frontmatter.block_span`) -- CLAUDE.md can hold more than one
embedded persona, so an unscoped edit could touch the wrong one's block.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from . import frontmatter


@dataclass
class DiscoveredPersona:
    slug: str
    fields: dict
    markdown_path: Path
    embedded: bool


def _load_markdown_fields(markdown_path: Path) -> dict | None:
    try:
        text = markdown_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return frontmatter.extract_frontmatter(text)


def discover_personas(root: Path) -> list[DiscoveredPersona]:
    claude_md = root / "CLAUDE.md"
    if not claude_md.is_file():
        return []
    try:
        text = claude_md.read_text(encoding="utf-8")
    except OSError:
        return []

    personas: list[DiscoveredPersona] = []
    for slug in frontmatter.find_marker_slugs(text):
        ref = frontmatter.extract_ref_import(text, slug)
        if ref:
            target = root / ref
            fields = _load_markdown_fields(target)
            if fields:
                personas.append(DiscoveredPersona(slug, fields, target, embedded=False))
            continue
        embedded_fields = frontmatter.extract_embedded_block(text, slug)
        if embedded_fields:
            personas.append(DiscoveredPersona(slug, embedded_fields, claude_md, embedded=True))
    return personas


# An agent-team member is its own `claude` process carrying `--agent-name <name>` (and
# `--team-name`, `--parent-session-id`). It shares the lead's project directory, so the project's
# CLAUDE.md names the *lead's* persona -- read on its own, that put the lead's face and name on
# every member of every team. The member's own persona lives where profile-gen's `--output file`
# writes one, keyed by the same name the team gave it: profiles/<name>/<name>.md (tracked) or
# .profiles-assets/<name>/<name>.md (gitignored). Claude Buddy's orb resolver looks in exactly
# these two places for the same reason (CB-154), so one persona file serves both.
_AGENT_NAME = re.compile(r"--agent-name(?:=|\s+)([A-Za-z0-9._-]+)")

# For tests, and for a launcher that knows better than the process table.
AGENT_NAME_ENV = "PROFILEGEN_AGENT_NAME"


def _ancestor_args_posix(pid: int) -> list[str]:
    args = []
    for _ in range(12):
        if pid <= 1:
            break
        try:
            out = subprocess.run(
                ["ps", "-o", "ppid=,args=", "-p", str(pid)],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            break
        parts = out.split(None, 1)
        if not parts:
            break
        args.append(parts[1] if len(parts) > 1 else "")
        try:
            pid = int(parts[0])
        except ValueError:
            break
    return args


def agent_name_from_args(command_lines: list[str]) -> str | None:
    """The first `--agent-name` found walking up from this process -- nearest ancestor wins."""
    for line in command_lines:
        match = _AGENT_NAME.search(line)
        if match and match.group(1) not in (".", ".."):
            return match.group(1)
    return None


def current_agent_name() -> str | None:
    """This session's agent-team name, or None for an ordinary session.

    Windows has no `ps`; there the env override is the only route and a team member falls back to
    the project persona, which is the behaviour before this existed rather than a new failure.
    """
    override = os.environ.get(AGENT_NAME_ENV)
    if override is not None:
        return agent_name_from_args([f"--agent-name {override}"]) if override else None
    if sys.platform.startswith("win"):
        return None
    try:
        return agent_name_from_args(_ancestor_args_posix(os.getppid()))
    except Exception:
        return None


def agent_persona(root: Path, name: str) -> DiscoveredPersona | None:
    for relative in (Path("profiles") / name / f"{name}.md", Path(".profiles-assets") / name / f"{name}.md"):
        path = root / relative
        if path.is_file():
            fields = _load_markdown_fields(path)
            if fields:
                return DiscoveredPersona(fields.get("slug") or name, fields, path, embedded=False)
    return None


def discover_for_session(root: Path, agent_name: str | None = None) -> list[DiscoveredPersona]:
    """What *this* session should wear.

    A team member with its own persona file gets that one. A team member without one gets
    nothing at all -- no badge beats the lead's badge, because a wrong face is read as a fact about
    who is talking while a missing one is only a gap. Everything else gets the project personas.
    """
    name = agent_name if agent_name is not None else current_agent_name()
    if name:
        own = agent_persona(root, name)
        return [own] if own else []
    return discover_personas(root)
