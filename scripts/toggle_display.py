#!/usr/bin/env python3
"""CLI: flip a persona's stored display preferences (image/name/autostart/variant) in place.

Discovers personas the same way show_profile.py does (via the profile-gen marker blocks of the
nearest CLAUDE.md at or above <root> that has any) and edits whichever markdown file that persona's content actually lives in --
persona.md/profiles/<slug>/<slug>.md for claude-md-ref, or the right slug's own marker-delimited
region inside CLAUDE.md itself for a fully-embedded (claude-md) persona. Only the display: block
is touched; nothing else in the file is regenerated or reformatted.

At least one of --image/--name/--autostart/--variant is required. --image/--name control what is
drawn; --autostart controls whether a SessionStart hook shows this persona on its own, which is a
separate question -- a persona can stay quiet at startup while still displaying when asked for.
--variant sfw|nsfw|toggle picks which of the persona's two pictures is shown (their SFW `image`
or their optional `image_nsfw`); `toggle` flips whichever is stored now. Switching to a variant
the persona has no picture for is refused rather than silently ignored, so `/display-profile nsfw
on` against a persona with no NSFW picture says so.

A persona written before a flag existed simply has it appended to its display: block. Prints one
JSON object per persona changed: {"slug", "markdown_path", "display": {...}}, or
{"error": "..."} (nonzero exit) if nothing was found to change.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import discovery, frontmatter, variants  # noqa: E402


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
    parser.add_argument(
        "--autostart",
        choices=["on", "off"],
        help="whether a SessionStart hook shows this persona automatically",
    )
    parser.add_argument(
        "--variant",
        choices=["sfw", "nsfw", "toggle"],
        help="which picture to show: the SFW one, the NSFW one, or flip to the other",
    )
    args = parser.parse_args()

    if args.image is None and args.name is None and args.autostart is None and args.variant is None:
        _fail(
            "nothing to do: pass --image, --name and/or --autostart as on|off, "
            "and/or --variant as sfw|nsfw|toggle"
        )
        return

    root = Path(args.root).resolve()
    personas = discovery.discover_nearest(root)
    if args.slug:
        personas = [p for p in personas if p.slug == args.slug]

    if not personas:
        _fail("no persona found (is CLAUDE.md missing a profile-gen block, or --slug wrong?)")
        return

    image = (args.image == "on") if args.image else None
    name = (args.name == "on") if args.name else None
    autostart = (args.autostart == "on") if args.autostart else None

    results = []
    for persona in personas:
        variant = None
        if args.variant:
            current = variants.stored_variant(persona.fields)
            variant = variants.other(current) if args.variant == "toggle" else args.variant
            if not variants.has(persona.fields, variant):
                _fail(f"{persona.slug} {variants.missing_reason(persona.fields, variant)}")
                return

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
            new_text = frontmatter.set_display_flags(
                text,
                image=image,
                name=name,
                autostart=autostart,
                variant=variant,
                region=region,
            )
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
