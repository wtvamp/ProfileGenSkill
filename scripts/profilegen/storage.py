"""Path policy and idempotent file edits for profile-gen output.

Two independent choices drive where things land:

  --output  claude-md | claude-md-ref | file
  --assets  tracked   | gitignored

+---------------+------------+-----------------------------------+-------------------------+
| output        | assets     | markdown                          | asset dir               |
+---------------+------------+-----------------------------------+-------------------------+
| file          | tracked    | profiles/<slug>/<slug>.md          | profiles/<slug>/         |
| file          | gitignored | .profiles-assets/<slug>/<slug>.md  | .profiles-assets/<slug>/ |
| claude-md-ref | tracked    | profiles/<slug>/<slug>.md          | profiles/<slug>/         |
| claude-md-ref | gitignored | .claude/persona/persona.md         | .claude/persona/         |
| claude-md     | tracked    | ./CLAUDE.md (full block)           | profiles/<slug>/         |
| claude-md     | gitignored | ./CLAUDE.md (full block)           | .profiles-assets/<slug>/ |
+---------------+------------+-----------------------------------+-------------------------+

``file`` and ``claude-md-ref`` (when tracked) co-locate the persona's own markdown with its
asset directory.

``claude-md-ref`` additionally keeps a one-line ``@<relative path>`` import for the persona in
the project's real ``CLAUDE.md`` (Claude Code's own file-import syntax -- which only resolves a
specific file, not a bare directory), replaced in place on regeneration -- so a private persona
is still automatically discovered by anyone opening the project, without its content ever being
inlined into a tracked file.

``claude-md-ref`` + ``gitignored`` (the recommended combo for a private/NSFW persona) uses a
**fixed, generic path** -- ``.claude/persona/persona.md`` -- instead of one derived from the
persona's name, matching the hand-rolled convention this was modeled on (a project's `CLAUDE.md`
importing a fixed `@.claude/PERSONA.md` while that file's own content, not its path, carries the
identity). The tracked `@`-import string is therefore always the same literal text no matter who
the persona is -- nothing about their identity leaks into a tracked file. This means only **one**
private/gitignored persona is addressable this way per project at a time; regenerating with a
different name overwrites the previous one at that same fixed path. Images alongside
``persona.md`` (``persona.png``, ``persona.gif``, an auto-built ComfyUI ``workflow.json``, etc.)
are only ever referenced from within ``persona.md`` itself (never from the tracked CLAUDE.md
directly), so their names don't matter for privacy -- generic names are used for tidiness only.

A user wanting multiple simultaneous private personas, or a persona meant to be shared/committed
as-is, should use ``--assets tracked`` (visible, slug-named, supports any number of personas) or
``--output claude-md`` (fully inlined, appropriate when the content itself is meant to be
committed).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_GITIGNORE_PATTERN = ".profiles-assets/"

_PRIVATE_GITIGNORE_PATTERN = ".claude/persona/"
_PRIVATE_MARKER_KEY = "persona"

_SLUG_INVALID_RE = re.compile(r"[^a-z0-9]+")

_STANDALONE_MD_OUTPUTS = ("file", "claude-md-ref")


def slugify(name: str) -> str:
    slug = _SLUG_INVALID_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "profile"


def _is_private_reference(output: str, assets: str) -> bool:
    return output == "claude-md-ref" and assets == "gitignored"


def gitignore_pattern_for(output: str, assets: str) -> str:
    """The .gitignore line that should be ensured for this output/assets combo."""
    return _PRIVATE_GITIGNORE_PATTERN if _is_private_reference(output, assets) else _GITIGNORE_PATTERN


def plan_paths(root: str | Path, slug: str, output: str, assets: str) -> dict:
    """Return the final markdown_path/asset_dir (and marker_key) for the given output/assets
    combo.

    ``claude-md-ref`` + ``gitignored`` is special-cased to the fixed
    ``.claude/persona/persona.md`` path (see module docstring) -- every other combo derives its
    path from ``slug`` as usual.

    ``marker_key`` is what the CLAUDE.md marker comment / ``@`` import path uses to identify
    this persona: the human-readable ``slug`` normally, or the fixed string ``"persona"`` for the
    private combo above.
    """
    root = Path(root)

    if _is_private_reference(output, assets):
        asset_dir = root / ".claude" / "persona"
        markdown_path = asset_dir / "persona.md"
        return {
            "markdown_path": str(markdown_path),
            "asset_dir": str(asset_dir),
            "marker_key": _PRIVATE_MARKER_KEY,
        }

    if assets == "tracked":
        asset_dir = root / "profiles" / slug
    elif assets == "gitignored":
        asset_dir = root / ".profiles-assets" / slug
    else:
        raise ValueError(f"unknown assets policy: {assets!r}")

    if output == "claude-md":
        markdown_path = root / "CLAUDE.md"
    elif output in _STANDALONE_MD_OUTPUTS:
        markdown_path = asset_dir / f"{slug}.md"
    else:
        raise ValueError(f"unknown output policy: {output!r}")

    return {
        "markdown_path": str(markdown_path),
        "asset_dir": str(asset_dir),
        "marker_key": slug,
    }


def ensure_gitignore(root: str | Path, pattern: str = _GITIGNORE_PATTERN) -> bool:
    """Idempotently ensure ``pattern`` is present as a line in ``root/.gitignore``.

    Returns True if the file was created or modified, False if the pattern
    was already present.
    """
    root = Path(root)
    gitignore_path = root / ".gitignore"

    if not gitignore_path.exists():
        gitignore_path.write_text(pattern + "\n", encoding="utf-8")
        return True

    existing = gitignore_path.read_text(encoding="utf-8")
    lines = existing.splitlines()
    if pattern in lines:
        return False

    if existing and not existing.endswith("\n"):
        existing += "\n"
    gitignore_path.write_text(existing + pattern + "\n", encoding="utf-8")
    return True


def _marker_block_re(slug: str) -> "re.Pattern[str]":
    start = re.escape(f"<!-- profile-gen:start slug={slug} -->")
    end = re.escape(f"<!-- profile-gen:end slug={slug} -->")
    return re.compile(rf"{start}.*?{end}\n?", re.DOTALL)


def _replace_or_append_block(existing: str, slug: str, block: str) -> str:
    """Return ``existing`` with the profile-gen block for ``slug`` replaced in place if
    present, or appended (with a blank-line separator) otherwise.
    """
    block = block if block.endswith("\n") else block + "\n"
    block_re = _marker_block_re(slug)

    if block_re.search(existing):
        return block_re.sub(block, existing, count=1)
    if existing.strip():
        sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
        return existing + sep + block
    return block


def write_markdown_output(
    root: str | Path, output: str, assets: str, slug: str, rendered_md: str
) -> str:
    """Write ``rendered_md`` to the location dictated by ``output``/``assets``.

    ``assets`` is required to disambiguate the tracked vs. gitignored layouts for
    ``file``/``claude-md-ref`` -- see ``plan_paths``, which this function delegates to for the
    exact path.

    For ``output`` in (``file``, ``claude-md-ref``), ``rendered_md`` is the persona's full
    standalone content; the containing directory is created and the file is overwritten.

    For ``output == "claude-md"``, ``rendered_md`` must be the
    ``<!-- profile-gen:start slug=... --> ... <!-- profile-gen:end ... -->`` block. If a block
    with this slug already exists in CLAUDE.md, it is replaced in place; otherwise the block is
    appended (with a blank-line separator).

    Returns the path written to, as a string.
    """
    root = Path(root)
    paths = plan_paths(root, slug, output, assets)
    markdown_path = Path(paths["markdown_path"])

    if output in _STANDALONE_MD_OUTPUTS:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(rendered_md, encoding="utf-8")
        return str(markdown_path)

    if output == "claude-md":
        existing = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else ""
        new_content = _replace_or_append_block(existing, paths["marker_key"], rendered_md)
        markdown_path.write_text(new_content, encoding="utf-8")
        return str(markdown_path)

    raise ValueError(f"unknown output policy: {output!r}")


def write_claude_md_reference(root: str | Path, marker_key: str, target_path: str | Path) -> str:
    """Ensure a one-line ``@<relative path>`` import keyed by ``marker_key`` is present in
    ``root/CLAUDE.md`` (Claude Code's own file-import syntax), replacing any previous
    reference under the same key in place. Used by ``output == "claude-md-ref"`` so a persona's
    own markdown is never inlined into a tracked file -- only a tiny, content-free pointer to it
    is.

    ``marker_key`` should be ``plan_paths(...)["marker_key"]`` for this persona -- the fixed
    string ``"persona"`` for the private (gitignored) case, so the persona's identity doesn't
    leak into this tracked reference string either.

    Returns the CLAUDE.md path written to, as a string.
    """
    root = Path(root)
    claude_md_path = root / "CLAUDE.md"
    target = Path(target_path)

    try:
        rel = target.relative_to(root)
    except ValueError:
        rel = Path(os.path.relpath(target, root))

    block = (
        f"<!-- profile-gen:start slug={marker_key} -->\n"
        f"@{rel.as_posix()}\n"
        f"<!-- profile-gen:end slug={marker_key} -->\n"
    )

    existing = claude_md_path.read_text(encoding="utf-8") if claude_md_path.exists() else ""
    new_content = _replace_or_append_block(existing, marker_key, block)
    claude_md_path.write_text(new_content, encoding="utf-8")
    return str(claude_md_path)
