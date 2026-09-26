"""Which of a persona's two pictures is the one to show.

A persona has a **SFW picture** and, optionally, an **NSFW picture** (``image_nsfw``) -- the
same character, generated from the same seed and base prompt with the NSFW clause added, so the
two read as one person rather than two. ``display.variant`` records which of them is currently on
screen, and `/display-profile nsfw on|off|toggle` flips it.

``image`` is always **the picture currently selected**, not the SFW one. That is what lets a
generic profile reader -- anything that just takes a markdown file's ``image:`` or its first
``![...](...)``, with no idea this module exists -- show the right picture. So a persona that has
both variants stores each under its own key (``image_sfw`` and ``image_nsfw``), and a toggle
rewrites ``image:`` and the body's picture link to whichever is selected (see
``frontmatter.set_active_image``).

A two-variant persona written before ``image_sfw`` existed has no ``image_sfw`` and an ``image``
that is always its SFW picture, whatever ``display.variant`` says; ``paths()`` reads it that way,
and the first toggle under this module adds ``image_sfw`` before moving ``image``.

Top-level ``nsfw:`` therefore no longer means "this persona's one picture is explicit" -- it
means **an NSFW variant exists**. That reinterpretation is what makes profiles written before
this module still work:

  legacy ``nsfw: true`` with no ``image_nsfw``
      The single ``image`` *is* the NSFW picture and there is no SFW one. ``paths()`` reports it
      under ``nsfw`` only, so a persona like this displays exactly as it always did, and asking
      for ``sfw`` reports "unavailable" rather than quietly showing the explicit picture.

  legacy ``nsfw: false``
      Ordinary SFW-only persona; identical behaviour to before.

Resolution never fails hard and never substitutes the wrong kind of picture silently: asking for
a variant a persona doesn't have falls back to the one it does, and says so in
``Resolution.fell_back`` so the caller can mention it.
"""
from __future__ import annotations

from dataclasses import dataclass

SFW = "sfw"
NSFW = "nsfw"
VARIANTS = (SFW, NSFW)
DEFAULT_VARIANT = SFW


def other(variant: str) -> str:
    """The variant that isn't this one."""
    return SFW if variant == NSFW else NSFW


def normalize(variant: object) -> str:
    """Coerce a stored/CLI variant value to one of ``VARIANTS``, defaulting to ``sfw``."""
    if isinstance(variant, str) and variant.strip().lower() in VARIANTS:
        return variant.strip().lower()
    return DEFAULT_VARIANT


def paths(fields: dict) -> dict[str, str]:
    """``{variant: image path}`` for the variants this persona actually has a picture for.

    Paths are returned exactly as stored (project-root-relative, per
    references/profile-schema.md) -- resolving them against a root is the caller's job.
    """
    image = fields.get("image") or None
    image_sfw = fields.get("image_sfw") or None
    image_nsfw = fields.get("image_nsfw") or None

    if image_sfw:
        # `image` is only the currently selected copy; the variants live under their own keys.
        available = {SFW: str(image_sfw)}
        if image_nsfw:
            available[NSFW] = str(image_nsfw)
        return available

    if image_nsfw is None and fields.get("nsfw") and image:
        # Legacy single-image NSFW persona: its one picture is the NSFW one (see module docstring).
        return {NSFW: str(image)}

    available: dict[str, str] = {}
    if image:
        available[SFW] = str(image)
    if image_nsfw:
        available[NSFW] = str(image_nsfw)
    return available


def stored_variant(fields: dict) -> str:
    """The variant this persona's ``display.variant`` asks for (``sfw`` when unset)."""
    display = fields.get("display") if isinstance(fields.get("display"), dict) else {}
    return normalize(display.get("variant"))


def has(fields: dict, variant: str) -> bool:
    """Whether this persona has a picture for ``variant``."""
    return normalize(variant) in paths(fields)


@dataclass
class Resolution:
    requested: str
    """The variant that was asked for -- the override, or the persona's stored preference."""
    variant: str | None
    """The variant actually resolved to, or None when the persona has no picture at all."""
    path: str | None
    """That variant's stored image path, or None."""
    fell_back: bool
    """True when ``requested`` had no picture and the other variant was used instead."""


def resolve(fields: dict, override: str | None = None) -> Resolution:
    """Pick the picture to show: ``override`` if given, else ``display.variant``, falling back
    to whichever variant the persona does have when the requested one is missing."""
    requested = normalize(override) if override else stored_variant(fields)
    available = paths(fields)

    if requested in available:
        return Resolution(requested, requested, available[requested], fell_back=False)

    fallback = other(requested)
    if fallback in available:
        return Resolution(requested, fallback, available[fallback], fell_back=True)

    return Resolution(requested, None, None, fell_back=False)


def missing_reason(fields: dict, variant: str) -> str:
    """Why this persona has no picture for ``variant``, phrased for a user.

    The legacy shape needs its own wording: ``image`` *is* set there, it is just recorded as the
    explicit picture, so "image is unset" would read as plainly wrong to anyone looking at the
    file.
    """
    variant = normalize(variant)
    legacy = fields.get("nsfw") and not fields.get("image_nsfw") and fields.get("image")

    if variant == NSFW:
        return "has no nsfw picture (image_nsfw is unset) -- generate one with /profile-gen"
    if legacy:
        return (
            "has no sfw picture: it predates variants, so its only picture is recorded as the "
            "explicit one (nsfw: true with no image_nsfw). Generate a SFW picture with "
            "/profile-gen, or set nsfw: false in the profile if that picture is already safe"
        )
    return "has no sfw picture (image is unset) -- generate one with /profile-gen"
