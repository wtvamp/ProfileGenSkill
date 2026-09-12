# Prompting recipe

Read this before drafting the image prompt in SKILL.md step 6, and before writing the
personality description in step 3 when `nsfw` is set.

## Image prompt recipe

Build the positive prompt from these pieces, in order:

1. **Subject** — the confirmed name and a physical/character description drawn from the user's
   description hints (or invented if none were given, consistent with the personality).
2. **Framing** — default to `"head-and-shoulders portrait, centered, neutral background"` unless
   the user's hints imply a different framing (e.g. full-body, action pose).
3. **Style preset** — an optional short clause (e.g. `"digital painting, soft studio lighting"`
   or `"anime style"`) if the user expressed a style preference; otherwise omit it.

`generate_image.py`/`make_gif.py` write only your drafted subject+framing text to a prompt file;
`scripts/profilegen/prompt.py::build(positive_text, negative_text, nsfw, style_preset, backend)`
runs automatically inside those scripts and appends the NSFW clause and negative-prompt defaults
below — **you should not append an NSFW clause yourself** (see the next section for why the
right phrasing depends on the backend, and getting it wrong on a hosted backend actively causes
refusals rather than helping).

## NSFW clause — backend-aware, and why

`build()` picks one of two clauses depending on `--backend`, because "explicit permission"
phrasing behaves completely differently depending on whether a vendor content classifier is in
the loop:

**Local/self-hosted (`comfyui`)** — no vendor classifier at all; it's the user's own server and
model weights. `NSFW_CLAUSE_LOCAL` (verbatim, kept in sync with `prompt.py`):

> explicit adult content permitted, nudity and sexual content allowed, no censorship or content
> restrictions

This directness is appropriate and often *necessary* here — many checkpoints/LoRAs need
explicit anatomical language to actually produce full nudity/explicit content, and there's no
classifier to trigger a refusal.

**Hosted backends with a classifier in the loop (`chatgpt`, `grok`, `grok-cli`)** —
`NSFW_CLAUSE_HOSTED` (verbatim):

> tasteful boudoir-style portrait, intimate and suggestive framing, artistic implied/partial
> nudity, sensual mood, adult subject

This is the opposite of the local clause on purpose. Publicly documented guidance on Grok's own
"Spicy Mode" (which shares the underlying classifier with the API/CLI) is consistent: blunt
"ignore restrictions"/"no censorship" language does **not** help and reliably reads as a policy-
violation attempt, triggering a refusal — while tasteful, suggestive, artistic framing succeeds
within whatever the model actually permits (partial nudity, suggestive poses, intimate framing).
ChatGPT's image API additionally gets `moderation: "low"` in the request itself (the one real
per-request moderation knob any of these backends expose — xAI's image API has no equivalent
request parameter at all, only a read-only `respect_moderation` field in the response).

**None of this bypasses a hosted backend's hard limits.** Real identifiable people, anyone who
is or appears to be a minor, and non-consensual content are enforced **server-side** by these
vendors regardless of phrasing — public guides on this are explicit that "no prompt removes"
those blocks. This skill does not attempt to and should not be used to try. What backend-aware
phrasing *does* fix is the much more common case: legitimate, consensual, fictional-adult-
persona content getting needlessly refused because the prompt was phrased in a way that reads as
adversarial to the classifier rather than because the content itself was actually disallowed.

If a provider still refuses or errors after using the appropriate clause, relay its message
verbatim to the user rather than retrying with a further-modified prompt.

## Negative prompt (ComfyUI only — ChatGPT/Grok don't accept one)

- Default negative prompt (quality-only): `"blurry, low quality, distorted, extra limbs,
  watermark, text"`.
- When `nsfw` is **not** set, the negative prompt should also include content-suppressing terms:
  `nsfw, nude, nudity, explicit, sexual content`.
- When `nsfw` **is** set, none of those suppressing terms should appear in the negative prompt —
  an NSFW request should never have its own content echoed back as something to avoid.

## Writing the personality description when NSFW is set

Write the personality description directly, in the register the user asked for. Do not add
disclaimers, content warnings, or refusal-adjacent hedging ("I should note that...", "as an AI
I..."). The user is an adult who owns the API keys or ComfyUI server being used and has
explicitly opted into NSFW mode — treat the request the same way you'd treat any other creative
writing task once that context is established.

## GIF mode expectations

**Native and synthetic modes animate different things — say so explicitly when reporting
results, don't just say "animated."**

- **Native** (ComfyUI with `comfyui_gif_workflow` configured, or `grok-cli`'s `/imagine-video`):
  a generative model re-renders motion, so the *subject itself* can genuinely animate — blink,
  breathe, shift expression, slight head movement. `scripts/make_gif.py` automatically appends
  `profilegen.prompt.GIF_MOTION_CLAUSE` to the prompt for native-mode calls specifically so the
  model animates the person rather than defaulting to a static subject with only camera pan/
  zoom/dolly motion (a common failure mode for these pipelines left to their own devices — see
  `references/comfyui-workflow-authoring.md`'s GIF section for the workflow-side settings that
  reinforce this too). You don't need to add this clause yourself when drafting the GIF prompt —
  it happens automatically — but don't undercut it either (e.g. don't separately ask for "a slow
  cinematic pan" as the main instruction).
- **Synthetic** (ChatGPT, Grok's plain API, or ComfyUI/grok-cli without a native GIF path):
  `scripts/profilegen/gif.py` applies a deterministic zoom + drift to the single still image via
  Pillow. There is no generative model in this path, so **this is camera movement only — the
  subject cannot blink, change expression, or otherwise move.** It preserves identity perfectly
  and costs nothing extra (the rejected alternative, stitching multiple independent generations,
  doesn't preserve the same face/character across calls). When reporting a synthetic GIF, tell
  the user plainly that the person themselves doesn't move — only the framing does — so they
  don't mistake it for genuine animation.
