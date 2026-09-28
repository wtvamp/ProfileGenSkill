"""NSFW-aware prompt building — pure string logic, no backend/network dependencies.

The NSFW flag is a pass-through: this module's job is to (a) append an appropriate clause to the
positive prompt when nsfw is requested, and (b) keep the default negative prompt's
content-suppressing terms out of the way when nsfw is requested (and present when it is not). It
never blocks or waters down a prompt itself — that decision belongs to the user and whichever
backend they've pointed the skill at. It also never attempts to get past a backend's hard,
non-negotiable limits (real identifiable people, minors, non-consensual content) — those are
enforced server-side by hosted backends regardless of prompt phrasing, and this skill doesn't
try to route around them.

**The clause is backend-aware, because "explicit permission" phrasing behaves completely
differently depending on whether there's a vendor content classifier in the loop:**

- **Local/self-hosted (ComfyUI)**: there's no vendor classifier at all -- it's the user's own
  server and model weights. Blunt, explicit language (``NSFW_CLAUSE_LOCAL``) is appropriate and
  necessary here: a diffusion model renders what the prompt depicts, not what it permits, and
  Pony-family checkpoints also need rating tags (``PONY_NSFW_PREFIX``).
- **Hosted APIs with a classifier in the loop (Grok, Grok CLI, ChatGPT)**: blunt "ignore
  restrictions"/"no censorship" language does NOT help here and reliably triggers refusals --
  publicly documented guidance on prompting Grok's own "Spicy Mode" (which uses the same
  underlying classifier as the API) consistently says the opposite works better: tasteful,
  suggestive, artistic framing (``NSFW_CLAUSE_HOSTED`` -- boudoir-style, intimate, implied/
  partial nudity) succeeds within whatever envelope the model actually permits, while explicit
  anatomical/pornographic requests get blocked regardless of how they're phrased. Nothing here
  bypasses a hosted backend's hard limits (real people, minors, non-consensual) -- those are
  enforced server-side and no prompt phrasing removes them; this is only about not
  *needlessly* triggering a refusal on content the backend would otherwise allow.

Also owns ``GIF_MOTION_CLAUSE``/``add_gif_motion_clause`` -- native (generative) GIF/video
backends left to their own devices commonly produce a static subject with only camera pan/zoom
motion (a "Ken Burns" effect), which is indistinguishable from what the synthetic GIF path
already does for free. ``scripts/make_gif.py`` applies this clause to every native-mode prompt
so the request is unambiguous: animate the *person*, not the camera.
"""
from __future__ import annotations

# Appropriate for local/self-hosted backends only (ComfyUI) -- no vendor classifier is involved.
# This must be *visual* language: a diffusion model renders what a prompt depicts, and
# permission-style wording ("explicit content permitted, no censorship") depicts nothing, so it
# used to produce a fully clothed "NSFW" variant. Concrete descriptors are what actually render.
NSFW_CLAUSE_LOCAL = (
    "nude, topless, bare breasts, bare skin, sensual pose, intimate boudoir setting"
)

# Pony-family checkpoints (Pony Diffusion and merges such as cyberrealisticPony) are trained on
# score/rating tags and default to rating_safe without them, so an NSFW request on such a
# checkpoint needs the tags up front and the safe/clothed tags pushed into the negative.
PONY_NSFW_PREFIX = "score_9, score_8_up, score_7_up, rating_explicit"
PONY_NSFW_NEGATIVE_TERMS = ["rating_safe", "clothed", "clothes", "dress", "shirt"]

# Appropriate for hosted backends with a vendor classifier in the loop (Grok, Grok CLI, ChatGPT).
# Suggestive/artistic framing rather than an explicit override request -- see module docstring.
NSFW_CLAUSE_HOSTED = (
    "tasteful boudoir-style portrait, intimate and suggestive framing, artistic implied/partial "
    "nudity, sensual mood, adult subject"
)

# Backward-compatible alias -- historically the only clause, now the local-backend variant.
NSFW_CLAUSE = NSFW_CLAUSE_LOCAL

_HOSTED_BACKENDS = {"chatgpt", "grok", "grok-cli"}

GIF_MOTION_CLAUSE = (
    "the subject itself is animated with subtle natural motion — gentle blinking, soft "
    "breathing, slight head movement, small natural micro-expressions — the person moves, "
    "not just the camera; avoid a static subject with only camera pan/zoom/dolly motion"
)

# Substring checked case-insensitively against an existing positive prompt to avoid appending
# GIF_MOTION_CLAUSE a second time on re-generation.
_GIF_MOTION_MARKER = "the subject itself is animated with subtle natural motion"

DEFAULT_NEGATIVE_SUPPRESSING_TERMS = [
    "nsfw",
    "nude",
    "nudity",
    "explicit",
    "sexual content",
]

DEFAULT_NEGATIVE_BASE = "blurry, low quality, distorted, extra limbs, watermark, text"

# Substrings checked case-insensitively against an existing positive prompt to avoid appending
# either NSFW clause a second time on re-generation, regardless of which variant was used before.
_NSFW_MARKER_LOCAL = "nude, topless, bare breasts"
# The pre-fix local clause -- still recognised so re-running on an old prompt adds no second clause.
_NSFW_MARKER_LOCAL_LEGACY = "explicit adult content permitted"
_NSFW_MARKER_HOSTED = "tasteful boudoir-style portrait"
_NSFW_MARKER = _NSFW_MARKER_LOCAL  # backward-compatible alias


def _nsfw_clause_for(backend: str | None) -> str:
    return NSFW_CLAUSE_HOSTED if backend in _HOSTED_BACKENDS else NSFW_CLAUSE_LOCAL


def build(
    positive_text: str,
    negative_text: str | None,
    nsfw: bool,
    style_preset: str | None = None,
    backend: str | None = None,
    checkpoint: str | None = None,
) -> tuple[str, str]:
    """Return (final_positive, final_negative) prompts.

    final_positive: positive_text, plus style_preset (if given), plus an NSFW clause (if nsfw
    and not already present) -- ``NSFW_CLAUSE_HOSTED`` for a hosted/classifier-gated backend
    (``chatgpt``/``grok``/``grok-cli``), ``NSFW_CLAUSE_LOCAL`` otherwise (``comfyui``, or
    ``backend`` omitted). See module docstring for why these differ.

    final_negative: negative_text if given, else DEFAULT_NEGATIVE_BASE; with the
    suppressing terms added when not nsfw, or stripped out when nsfw.

    checkpoint: the ComfyUI checkpoint name the workflow loads, if known. When nsfw is set and it
    names a Pony-family model (contains "pony", case-insensitive), ``PONY_NSFW_PREFIX`` is
    prepended to the positive and ``PONY_NSFW_NEGATIVE_TERMS`` are added to the negative.
    """
    parts = [positive_text.strip()] if positive_text and positive_text.strip() else []
    if style_preset and style_preset.strip():
        parts.append(style_preset.strip())
    existing_lower = (positive_text or "").lower()
    if nsfw and not any(
        m in existing_lower for m in (_NSFW_MARKER_LOCAL, _NSFW_MARKER_LOCAL_LEGACY, _NSFW_MARKER_HOSTED)
    ):
        parts.append(_nsfw_clause_for(backend))
    pony = bool(nsfw and checkpoint and "pony" in checkpoint.lower())
    if pony and "rating_explicit" not in existing_lower:
        parts.insert(0, PONY_NSFW_PREFIX)
    final_positive = ", ".join(parts)

    base_negative = negative_text.strip() if negative_text and negative_text.strip() else DEFAULT_NEGATIVE_BASE
    final_negative = _adjust_negative_terms(base_negative, nsfw)
    if pony:
        present = {t.strip().lower() for t in final_negative.split(",")}
        extra = [t for t in PONY_NSFW_NEGATIVE_TERMS if t not in present]
        if extra:
            final_negative = ", ".join([final_negative] + extra) if final_negative else ", ".join(extra)

    return final_positive, final_negative


def checkpoint_from_workflow(workflow: dict) -> str | None:
    """Return the checkpoint name an API-format ComfyUI workflow loads (the first
    ``ckpt_name`` input found), or None -- e.g. a Wan/LTX video workflow built on UNETLoader."""
    for node in (workflow or {}).values():
        if isinstance(node, dict):
            name = (node.get("inputs") or {}).get("ckpt_name")
            if isinstance(name, str) and name:
                return name
    return None


def add_gif_motion_clause(positive_text: str) -> str:
    """Append GIF_MOTION_CLAUSE to a positive prompt used for native (generative) GIF/video
    generation, unless a substantively equivalent clause is already present. This is what makes
    native mode actually animate the subject rather than perform a camera move over a static
    frame -- the one thing that would otherwise be indistinguishable from the synthetic GIF path.
    """
    text = (positive_text or "").strip()
    if _GIF_MOTION_MARKER in text.lower():
        return text
    if not text:
        return GIF_MOTION_CLAUSE
    return f"{text}, {GIF_MOTION_CLAUSE}"


def _adjust_negative_terms(negative: str, nsfw: bool) -> str:
    lowered = negative.lower()

    if nsfw:
        terms = [t.strip() for t in negative.split(",")]
        kept = [
            t
            for t in terms
            if t.strip() and not any(sup in t.strip().lower() for sup in DEFAULT_NEGATIVE_SUPPRESSING_TERMS)
        ]
        return ", ".join(kept)

    missing = [term for term in DEFAULT_NEGATIVE_SUPPRESSING_TERMS if term not in lowered]
    if not missing:
        return negative
    return ", ".join([negative] + missing) if negative else ", ".join(missing)
