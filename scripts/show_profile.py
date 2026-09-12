#!/usr/bin/env python3
"""CLI: display a profile-gen persona -- its picture and/or name -- in the user's terminal.

Two ways to point it at a persona:

  --root ROOT
      Default mode. Every persona currently auto-loaded via ROOT/CLAUDE.md's profile-gen marker
      blocks (the same blocks write_profile.py --output claude-md/claude-md-ref maintains).

  --profile PATH [--root ROOT]
      Exactly one profile's markdown file, skipping CLAUDE.md discovery -- used for the immediate
      preview right after profile-gen writes a persona. --root still matters: `image` fields are
      recorded relative to the project root (see references/profile-schema.md), not to the
      markdown file's own directory.

Two ways to actually draw it, chosen by --mode (default `auto`):

  state    iTerm2's badge (the name) and background image (the picture). These are terminal
           *state*, rendered outside the text grid, so they survive tmux and every redraw, and
           they persist until cleared -- which is the point, since the whole reason to show a
           persona is to keep knowing who you're talking to. Requires iTerm2.
  inline   An inline image painted into the text grid via termimg.py (iTerm2/WezTerm, Kitty,
           sixel). Works in a plain terminal, but inside tmux it degrades to a clipped sliver --
           tmux tracks only text cells and loses the image on the next repaint.
  auto     `state` when iTerm2 is detected (with or without tmux), else `inline`.
  off      Draw nothing. Useful with --clear.

--clear removes the badge/background instead of setting them.

When stdout is not a tty -- an agent's shell tool, whose output is captured for the model rather
than shown to the user -- `state` mode writes its escape sequences directly to the active tmux
pane's device instead, so the persona still reaches the real screen (see
profilegen/termstate.py). In that same case a one-line JSON summary of what was done is printed
to stdout for the calling program; when a human is watching a real terminal, nothing is printed.

Never errors out over a missing/malformed persona or an unsupported terminal -- a persona failing
to display is not worth interrupting a session over, especially from a SessionStart hook. Exits 0
in every "nothing to show" case.

Each persona's own `display.image`/`display.name` preference decides what's shown, defaulting to
true/true. --show-image/--no-image and --show-name/--no-name override that for this invocation
only, without touching the persona's stored preference (see toggle_display.py to change it).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import discovery, frontmatter, termimg, termstate  # noqa: E402


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


def _display_one(fields: dict, root: Path, args: argparse.Namespace, mode: str) -> dict:
    display = fields.get("display") if isinstance(fields.get("display"), dict) else {}
    show_image = args.show_image if args.show_image is not None else display.get("image", True)
    show_name = args.show_name if args.show_name is not None else display.get("name", True)

    name = fields.get("name")
    image_path = _resolve_image_path(fields.get("image"), root)
    result = {"name": name, "mode": mode, "badge": False, "background": False, "inline": False}

    if mode == "state":
        tty = termstate.resolve_target_tty()
        if show_name and name:
            result["badge"] = termstate.set_badge(str(name), tty)
        if show_image and image_path is not None and image_path.is_file():
            result["background"] = termstate.set_background_image(str(image_path), tty)
        return result

    if mode == "inline":
        if show_image and image_path is not None:
            result["inline"] = termimg.display_image(image_path, width_pct=args.width_pct)
        if show_name and name:
            print(f"\033[1m{name}\033[0m")
            result["badge"] = False
    return result


def _print_reports(reports: list[dict]) -> None:
    """One JSON object per line on stdout, for a calling program.

    The leading newline matters: escape sequences written to stdout (the fallback when there's no
    separate pane device to target) don't end in one, so without it the first report would be
    glued onto the tail of a sequence and wouldn't parse as a line of JSON.
    """
    if not reports:
        return
    sys.stdout.write("\n")
    for report in reports:
        print(json.dumps(report))


def _clear(args: argparse.Namespace) -> dict:
    tty = termstate.resolve_target_tty()
    return {
        "cleared_badge": termstate.clear_badge(tty),
        "cleared_background": termstate.clear_background_image(tty),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", default=".", help="project root personas are resolved against (default: cwd)"
    )
    parser.add_argument(
        "--profile", help="display exactly this one profile markdown file, skipping CLAUDE.md discovery"
    )
    parser.add_argument("--slug", help="only display the persona with this slug")
    parser.add_argument(
        "--mode",
        choices=["auto", "state", "inline", "off"],
        default="auto",
        help="how to draw: iTerm2 badge+background (state), in-grid image (inline), or auto",
    )
    parser.add_argument("--clear", action="store_true", help="remove the badge/background instead")
    parser.add_argument("--width-pct", type=int, default=10, help="inline image width as %% of terminal width")
    parser.add_argument("--show-image", dest="show_image", action="store_true", default=None)
    parser.add_argument("--no-image", dest="show_image", action="store_false")
    parser.add_argument("--show-name", dest="show_name", action="store_true", default=None)
    parser.add_argument("--no-name", dest="show_name", action="store_false")
    args = parser.parse_args()

    machine_readable = not sys.stdout.isatty()

    if args.clear:
        report = _clear(args)
        if machine_readable:
            _print_reports([report])
        return

    mode = args.mode
    if mode == "auto":
        mode = "state" if termstate.detect_iterm() else "inline"
    if mode == "off":
        return

    root = Path(args.root).resolve()
    reports = []

    if args.profile:
        fields = _load_markdown_fields(Path(args.profile))
        if fields:
            reports.append(_display_one(fields, root, args, mode))
    else:
        for persona in discovery.discover_personas(root):
            if args.slug and persona.slug != args.slug:
                continue
            reports.append(_display_one(persona.fields, root, args, mode))

    if machine_readable:
        _print_reports(reports)


if __name__ == "__main__":
    main()
