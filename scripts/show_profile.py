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

Three ways to actually draw it, chosen by --mode (default `auto`):

  hud      A small always-on-top, click-through overlay window floating over the terminal
           window, showing the picture (animated, for a GIF persona) and the name. macOS only.
           This is the default because it's the only option that consumes no terminal rows,
           touches no user configuration, and doesn't depend on terminal image protocols -- so
           tmux is irrelevant to it. See profilegen/hud.py and scripts/hud/PersonaHUD.swift.
  inline   An inline image painted into the text grid via termimg.py (iTerm2/WezTerm, Kitty,
           sixel). Works in a plain terminal, but inside tmux it degrades to a clipped sliver --
           tmux tracks only text cells and loses the image on the next repaint.
  state    iTerm2's badge (the name) and background image (the picture). Survives tmux, but it
           works by overwriting *user-owned* iTerm2 session settings: anyone with a configured
           background image loses it, and clearing sets empty rather than restoring theirs. Never
           chosen by `auto` for that reason -- it's opt-in only.
  auto     `hud` where supported, else `inline`.
  off      Draw nothing. Useful with --clear.

--clear stops the overlay and clears any badge/background left behind.

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

`display.autostart` is a separate question from those: it decides whether a persona appears *on
its own* at session start, not what gets drawn when it does. It's only consulted under
--autostart-only, which is what a SessionStart hook passes -- so a persona can be set to stay
quiet until asked for by `/display-profile` while still displaying normally when it is.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import discovery, frontmatter, hud, termimg, termstate  # noqa: E402


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
    result = {
        "name": name,
        "mode": mode,
        "hud": False,
        "badge": False,
        "background": False,
        "inline": False,
    }

    if mode == "hud":
        result["hud"] = hud.launch(
            str(image_path) if (show_image and image_path and image_path.is_file()) else None,
            str(name) if (show_name and name) else None,
            avatar=args.avatar,
            avatar_min=args.avatar_min,
            position=args.position,
            margin=args.margin,
        )
        return result

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
        "stopped_hud": hud.stop(),
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
        choices=["auto", "hud", "state", "inline", "off"],
        default="auto",
        help="how to draw: overlay window (hud), in-grid image (inline), "
        "iTerm2 badge+background (state -- overwrites user settings), or auto",
    )
    parser.add_argument("--clear", action="store_true", help="stop the overlay / clear badge+background")
    parser.add_argument(
        "--autostart-only",
        action="store_true",
        help="skip personas whose display.autostart is false (what a SessionStart hook uses)",
    )
    parser.add_argument(
        "--avatar", type=int, default=hud.DEFAULT_AVATAR,
        help="hud avatar's largest size in points; it shrinks to fit narrower tmux panes/windows",
    )
    parser.add_argument(
        "--avatar-min", type=int, default=hud.DEFAULT_AVATAR_MIN,
        help="hud avatar's smallest size in points, however narrow the pane gets",
    )
    parser.add_argument(
        "--position", "--corner", dest="position",
        choices=["tc", "c", "bc", "tr", "tl", "br", "bl"], default=hud.DEFAULT_POSITION,
        help="where in the pane/window the hud sits, as <vertical><horizontal> "
             "(default: tc, top centre)",
    )
    parser.add_argument(
        "--margin", type=int, default=hud.DEFAULT_MARGIN,
        help="hud inset from the edge, for whichever axis isn't centred",
    )
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
        # never auto-select `state`: it works by overwriting user-owned iTerm2 settings.
        mode = "hud" if hud.is_supported() else "inline"
    if mode == "off":
        return

    root = Path(args.root).resolve()
    reports = []

    def _autostart_allows(fields: dict) -> bool:
        if not args.autostart_only:
            return True
        display = fields.get("display") if isinstance(fields.get("display"), dict) else {}
        return bool(display.get("autostart", True))

    if args.profile:
        fields = _load_markdown_fields(Path(args.profile))
        if fields and _autostart_allows(fields):
            reports.append(_display_one(fields, root, args, mode))
    else:
        for persona in discovery.discover_personas(root):
            if args.slug and persona.slug != args.slug:
                continue
            if not _autostart_allows(persona.fields):
                continue
            reports.append(_display_one(persona.fields, root, args, mode))

    if machine_readable:
        _print_reports(reports)


if __name__ == "__main__":
    main()
