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
