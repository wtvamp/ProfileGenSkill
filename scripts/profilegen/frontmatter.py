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


def block_span(claude_md_text: str, slug: str) -> tuple[int, int] | None:
    """Character-offset ``(start, end)`` span of the ``<!-- profile-gen:start slug=... -->``
    ... ``<!-- profile-gen:end ... -->`` marker block for ``slug`` (markers included), or None if
    not present. Used to confine an edit (see ``set_display_flags``) to one persona's own region
    of a CLAUDE.md that may hold more than one embedded persona."""
    start_marker = f"<!-- profile-gen:start slug={slug} -->"
    end_marker = f"<!-- profile-gen:end slug={slug} -->"
    start_idx = claude_md_text.find(start_marker)
    if start_idx == -1:
        return None
    end_idx = claude_md_text.find(end_marker, start_idx)
    if end_idx == -1:
        return None
    return start_idx, end_idx + len(end_marker)


_DISPLAY_IMAGE_RE = r"(display:\n  image: )(?:true|false)"
_DISPLAY_NAME_RE = r"(display:\n  image: (?:true|false)\n  name: )(?:true|false)"


def set_display_flags(
    text: str,
    *,
    image: bool | None = None,
    name: bool | None = None,
    region: tuple[int, int] | None = None,
) -> str:
    """Flip ``display.image``/``display.name`` booleans in profile-gen's fixed
    ``display:\\n  image: <bool>\\n  name: <bool>`` block (the exact, unvarying shape
    `templates/*.j2` render -- see their module docstring). Only the flags actually passed
    (not ``None``) are changed; passing neither is a no-op.

    ``region`` confines the edit to that ``(start, end)`` character slice of ``text`` -- pass
    ``frontmatter.block_span(text, slug)`` when ``text`` is a CLAUDE.md that may hold more than
    one embedded persona's block, so a different persona's ``display:`` is never touched.
    Omit it for a persona's own standalone markdown file, which has exactly one such block.

    Raises ``ValueError`` if no ``display:`` block is found within the target region.
    """
    start, end = region if region is not None else (0, len(text))
    segment = text[start:end]

    if image is not None:
        segment, count = re.subn(
            _DISPLAY_IMAGE_RE, r"\g<1>" + ("true" if image else "false"), segment, count=1
        )
        if count == 0:
            raise ValueError("no display.image field found in the target region")

    if name is not None:
        segment, count = re.subn(
            _DISPLAY_NAME_RE, r"\g<1>" + ("true" if name else "false"), segment, count=1
        )
        if count == 0:
            raise ValueError("no display.name field found in the target region")

    return text[:start] + segment + text[end:]
