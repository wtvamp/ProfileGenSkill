"""Minimal, dependency-free reader for profile-gen's own generated markdown.

Not a general YAML parser -- it only understands the flat / one-level-nested subset that
`render.py`'s templates ever produce (see that module's docstring): top-level ``key: value``
lines, and a top-level key with no value followed by indented ``  key: value`` lines becoming one
level of nested dict. That is exactly what `templates/*.j2` emit for a profile's frontmatter
(``generation:``, ``display:``), so this is good enough to read back what this project writes --
it is not meant to survive hand-edited YAML that strays outside that shape.

Scalars coerce to string (quoted), bool (``true``/``false``), ``None`` (``null``/empty), or int
(anything else that parses as one, e.g. ``seed: 42``) -- otherwise the raw text is kept as a
plain string.
"""
from __future__ import annotations

import re

_TOP_KV_RE = re.compile(r"^([a-zA-Z0-9_]+):\s*(.*)$")
_NESTED_KV_RE = re.compile(r"^\s{2,}([a-zA-Z0-9_]+):\s*(.*)$")
_MARKER_RE = re.compile(r"<!-- profile-gen:start slug=([a-z0-9-]+) -->")
_IMPORT_RE = re.compile(r"^@(.+)$", re.MULTILINE)


def _coerce(raw: str) -> object:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return raw[1:-1]
    if raw == "true":
        return True
    if raw == "false":
        return False
    if raw in ("null", ""):
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


def parse_flat_yaml(text: str) -> dict:
    """Parse the flat/one-level-nested YAML subset described above into a dict."""
    result: dict = {}
    current_parent: str | None = None
    for line in text.splitlines():
        if not line.strip():
            continue
        nested = _NESTED_KV_RE.match(line)
        if nested and current_parent is not None:
            result[current_parent][nested.group(1)] = _coerce(nested.group(2))
            continue
        top = _TOP_KV_RE.match(line)
        if top:
            key, value = top.group(1), top.group(2)
            if value.strip() == "":
                result[key] = {}
                current_parent = key
            else:
                result[key] = _coerce(value)
                current_parent = None
    return result


def extract_frontmatter(markdown_text: str) -> dict | None:
    """Parse the ``---\\n...\\n---`` YAML frontmatter block at the top of a standalone
    profile-gen markdown file. Returns None if there is no such block."""
    if not markdown_text.startswith("---"):
        return None
    parts = markdown_text.split("---", 2)
    if len(parts) < 3:
        return None
    return parse_flat_yaml(parts[1])


def find_marker_slugs(claude_md_text: str) -> list[str]:
    """All profile-gen marker-block slugs present in a CLAUDE.md, in file order."""
    return _MARKER_RE.findall(claude_md_text)


def _block(claude_md_text: str, slug: str) -> str | None:
    start = f"<!-- profile-gen:start slug={slug} -->"
    end = f"<!-- profile-gen:end slug={slug} -->"
    if start not in claude_md_text:
        return None
    return claude_md_text.split(start, 1)[1].split(end, 1)[0]


def extract_ref_import(claude_md_text: str, slug: str) -> str | None:
    """The ``@<path>`` import line inside a claude-md-ref marker block for ``slug``, or None."""
    block = _block(claude_md_text, slug)
    if block is None:
        return None
    match = _IMPORT_RE.search(block)
    return match.group(1).strip() if match else None


def extract_embedded_block(claude_md_text: str, slug: str) -> dict | None:
    """Parse the fenced ```yaml block inside a claude-md (fully inlined) marker block for
    ``slug``. Returns None if that block, or its fenced YAML, isn't present."""
    block = _block(claude_md_text, slug)
    if block is None or "```yaml" not in block:
        return None
    fenced = block.split("```yaml", 1)[1].split("```", 1)[0]
    return parse_flat_yaml(fenced)
