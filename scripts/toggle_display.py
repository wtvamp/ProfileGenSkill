#!/usr/bin/env python3
"""CLI: flip a persona's stored display.image/display.name preference in place.

Discovers personas the same way show_profile.py does (via <root>/CLAUDE.md's profile-gen marker
blocks) and edits whichever markdown file that persona's content actually lives in --
persona.md/profiles/<slug>/<slug>.md for claude-md-ref, or the right slug's own marker-delimited
region inside CLAUDE.md itself for a fully-embedded (claude-md) persona. Only the display: block
is touched; nothing else in the file is regenerated or reformatted.

At least one of --image/--name is required. Prints one JSON object per persona changed:
{"slug", "markdown_path", "display": {"image": bool, "name": bool}}, or {"error": "..."}
(nonzero exit) if nothing was found to change.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import discovery, frontmatter  # noqa: E402


def _fail(message: str) -> None:
    print(json.dumps({"error": message}))
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", default=".", help="project root to discover personas under (default: cwd)"
    )
    parser.add_argument(
        "--slug", help="only touch the persona with this slug (default: all discovered personas)"
    )
    parser.add_argument("--image", choices=["on", "off"])
    parser.add_argument("--name", choices=["on", "off"])
    args = parser.parse_args()

    if args.image is None and args.name is None:
        _fail("nothing to do: pass --image on|off and/or --name on|off")
        return

    root = Path(args.root).resolve()
    personas = discovery.discover_personas(root)
    if args.slug:
        personas = [p for p in personas if p.slug == args.slug]

    if not personas:
        _fail("no persona found (is CLAUDE.md missing a profile-gen block, or --slug wrong?)")
        return

    image = (args.image == "on") if args.image else None
    name = (args.name == "on") if args.name else None

    results = []
    for persona in personas:
        try:
            text = persona.markdown_path.read_text(encoding="utf-8")
        except OSError as e:
            _fail(f"could not read {persona.markdown_path}: {e}")
            return

        region = None
        if persona.embedded:
            region = frontmatter.block_span(text, persona.slug)
            if region is None:
                _fail(f"could not locate marker block for slug {persona.slug}")
                return

        try:
            new_text = frontmatter.set_display_flags(text, image=image, name=name, region=region)
        except ValueError as e:
            _fail(f"{persona.markdown_path}: {e}")
            return

        persona.markdown_path.write_text(new_text, encoding="utf-8")

        if persona.embedded:
            updated_fields = frontmatter.extract_embedded_block(new_text, persona.slug)
        else:
            updated_fields = frontmatter.extract_frontmatter(new_text)

        results.append(
            {
                "slug": persona.slug,
                "markdown_path": str(persona.markdown_path),
                "display": (updated_fields or {}).get("display", {}),
            }
        )

    for result in results:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
