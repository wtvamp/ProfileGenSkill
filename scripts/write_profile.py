#!/usr/bin/env python3
"""CLI: plan output paths, or render+write a profile-gen profile to disk.

--root is REQUIRED and must be an absolute path to the user's actual project directory --
never omit it or rely on a default. This script's own location (under the skill's install
directory) has nothing to do with --root; passing the wrong directory here is what causes a
persona to be written inside the skill's installation instead of the target project.

Two modes:

  --plan-only --name NAME --root ROOT [--output ...] [--assets ...]
      Prints {"markdown_path": ..., "asset_dir": ...} and writes nothing.
      Called before image/gif generation so those scripts know exactly
      where to write their output files.

  --fields-file FIELDS.json --root ROOT [--output ...] [--assets ...]
      Loads the full profile fields, renders the markdown, writes it out,
      ensures .gitignore is updated when --assets gitignored, and (for
      --output claude-md-ref) keeps a one-line @-import for the persona in
      the project's CLAUDE.md. Prints {"markdown_path", "image_path",
      "gitignore_updated", "claude_md_updated", "claude_md_path"}
      on success, or {"error": "..."} (nonzero exit) on failure.

--output modes:
  file           standalone markdown, co-located with its assets (tracked or gitignored per
                 --assets); nothing else touched.
  claude-md-ref  same standalone markdown as `file`, PLUS a one-line `@<relative path>` import
                 kept in CLAUDE.md (replaced in place on regeneration) so a private
                 (gitignored) persona is still auto-discovered without inlining its content
                 into a tracked file. Recommended default for personal/NSFW personas. When
                 combined with --assets gitignored, both the on-disk path and the tracked
                 @-import string are the fixed, generic .claude/persona/persona.md -- never
                 derived from the persona's name -- so identity never leaks into a tracked
                 file (matches the hand-rolled convention this was modeled on). Only one such
                 private persona is addressable per project at a time; regenerating with a
                 different name overwrites it.
  claude-md      the full rendered profile is embedded directly in CLAUDE.md -- appropriate
                 when the persona itself is meant to be shared/committed as-is.

Fields file required keys: name, slug, image, nsfw, generation.
Optional keys: voice, personality.

There is a single `image` field -- it holds whichever file is the profile's final picture, a
static PNG or an animated GIF, never both. `generation.gif_mode` says which: null for a plain
static image, "native"/"synthetic" when `image` is an animated GIF.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import render, storage  # noqa: E402

REQUIRED_FIELD_KEYS = ("name", "slug", "image", "nsfw", "generation")


def _fail(message: str) -> None:
    print(json.dumps({"error": message}))
    sys.exit(1)


def _plan_only(args: argparse.Namespace) -> None:
    slug = storage.slugify(args.name)
    paths = storage.plan_paths(args.root, slug, args.output, args.assets)
    print(json.dumps(paths))


def _write(args: argparse.Namespace) -> None:
    try:
        raw = Path(args.fields_file).read_text(encoding="utf-8")
    except OSError as exc:
        _fail(f"could not read fields file: {exc}")
        return

    try:
        fields = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(f"fields file is not valid JSON: {exc}")
        return

    missing = [key for key in REQUIRED_FIELD_KEYS if key not in fields]
    if missing:
        _fail(f"fields file missing required keys: {', '.join(missing)}")
        return

    slug = fields.get("slug") or storage.slugify(fields["name"])

    try:
        if args.output == "claude-md":
            rendered = render.render_embedded(fields)
        else:
            rendered = render.render_standalone(fields)
    except FileNotFoundError as exc:
        _fail(f"template not found: {exc}")
        return

    try:
        markdown_path = storage.write_markdown_output(
            args.root, args.output, args.assets, slug, rendered
        )
    except (OSError, ValueError) as exc:
        _fail(f"could not write markdown output: {exc}")
        return

    claude_md_path = None
    if args.output == "claude-md-ref":
        marker_key = storage.plan_paths(args.root, slug, args.output, args.assets)["marker_key"]
        try:
            claude_md_path = storage.write_claude_md_reference(args.root, marker_key, markdown_path)
        except OSError as exc:
            _fail(f"could not write CLAUDE.md reference: {exc}")
            return
    elif args.output == "claude-md":
        claude_md_path = markdown_path

    gitignore_updated = False
    if args.assets == "gitignored":
        pattern = storage.gitignore_pattern_for(args.output, args.assets)
        gitignore_updated = storage.ensure_gitignore(args.root, pattern=pattern)

    print(
        json.dumps(
            {
                "markdown_path": markdown_path,
                "image_path": fields.get("image"),
                "gitignore_updated": gitignore_updated,
                "claude_md_updated": args.output in ("claude-md", "claude-md-ref"),
                "claude_md_path": claude_md_path,
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--fields-file")
    parser.add_argument("--name", help="required with --plan-only")
    parser.add_argument(
        "--root",
        required=True,
        help="absolute path to the user's actual project directory (never this skill's own "
        "install directory)",
    )
    parser.add_argument(
        "--output", choices=["claude-md", "claude-md-ref", "file"], default="claude-md-ref"
    )
    parser.add_argument(
        "--assets", choices=["tracked", "gitignored"], default="tracked"
    )
    args = parser.parse_args()

    if args.plan_only:
        if not args.name:
            _fail("--plan-only requires --name")
            return
        _plan_only(args)
        return

    if not args.fields_file:
        _fail("--fields-file is required unless --plan-only is given")
        return
    _write(args)


if __name__ == "__main__":
    main()
