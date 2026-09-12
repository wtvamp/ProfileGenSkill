#!/usr/bin/env python3
"""CLI: display a profile-gen persona's image and/or name inline in the current terminal.

Two ways to point it at a persona:

  --root ROOT [--profile PATH]
      Default mode. Discovers every persona currently auto-loaded via ROOT/CLAUDE.md's
      profile-gen marker blocks (the same blocks write_profile.py --output claude-md/
      claude-md-ref maintains) and displays each one. This is the mode meant for a SessionStart
      hook -- see references/terminal-display.md for wiring it up so a persona shows automatically
      at the start of every session in a project, not just right after generating one.

  --profile PATH [--root ROOT]
      Displays exactly one profile's markdown file directly, without touching CLAUDE.md at all
      -- used for the immediate preview right after profile-gen writes a new persona. --root
      still matters here: `image` fields are recorded relative to the project root (see
      references/profile-schema.md), not to the markdown file's own directory.

Never errors out over a missing/malformed persona or an unsupported terminal -- a persona
preview failing to show is not worth interrupting a session over, especially from a hook. Prints
nothing and exits 0 in every "nothing to show" case.

Each persona's own `display.image`/`display.name` preference (set at generation time, see
SKILL.md's --show-image/--show-name flags) decides what's shown, defaulting to true/true for a
persona predating this field. --show-image/--no-image and --show-name/--no-name override that
default for this invocation only, without touching the persona's stored preference.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import discovery, frontmatter, termimg  # noqa: E402


def _load_markdown_fields(markdown_path: Path) -> dict | None:
    try:
        text = markdown_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return frontmatter.extract_frontmatter(text)


def _resolve_image_path(image: object, root: Path) -> Path | None:
    if not image or not isinstance(image, str):
        return None
    path = Path(image)
    return path if path.is_absolute() else root / path


def _display_one(fields: dict, root: Path, args: argparse.Namespace) -> None:
    display = fields.get("display") if isinstance(fields.get("display"), dict) else {}
    show_image = args.show_image if args.show_image is not None else display.get("image", True)
    show_name = args.show_name if args.show_name is not None else display.get("name", True)

    if show_image:
        image_path = _resolve_image_path(fields.get("image"), root)
        if image_path is not None:
            termimg.display_image(image_path, width_pct=args.width_pct)

    name = fields.get("name")
    if show_name and name:
        print(f"\033[1m{name}\033[0m")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", default=".", help="project root personas are resolved against (default: cwd)"
    )
    parser.add_argument(
        "--profile", help="display exactly this one profile markdown file, skipping CLAUDE.md discovery"
    )
    parser.add_argument("--width-pct", type=int, default=10, help="image width as %% of terminal width (default: 10)")
    parser.add_argument("--show-image", dest="show_image", action="store_true", default=None)
    parser.add_argument("--no-image", dest="show_image", action="store_false")
    parser.add_argument("--show-name", dest="show_name", action="store_true", default=None)
    parser.add_argument("--no-name", dest="show_name", action="store_false")
    args = parser.parse_args()

    root = Path(args.root).resolve()

    if args.profile:
        fields = _load_markdown_fields(Path(args.profile))
        if fields:
            _display_one(fields, root, args)
        return

    for persona in discovery.discover_personas(root):
        _display_one(persona.fields, root, args)


if __name__ == "__main__":
    main()
