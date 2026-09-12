---
name: profile-gen
description: Generate a persona for an AI agent — a profile image (with optional animated GIF), a human-like name, an optional voice reference, and an optional personality description — and record it as a standalone markdown profile with a one-line auto-discoverable reference kept in CLAUDE.md (or, optionally, fully inlined into CLAUDE.md). Private/NSFW personas can be kept entirely out of git while still being auto-loaded via that reference. Supports ChatGPT/Grok (with an API key), the Grok CLI (no API key — uses a Grok/X subscription via `grok login`), or a self-hosted ComfyUI server (no account needed — the skill can author a workflow for you, LoRA picks included, if you don't already have one).
argument-hint: "[description hints] [--backend chatgpt|grok|grok-cli|comfyui] [--nsfw] [--gif] [--voice NAME] [--output claude-md-ref|claude-md|file] [--assets tracked|gitignored] [--name NAME] [--no-image] [--no-name]"
allowed-tools: Bash, Read, Write, Edit, AskUserQuestion, Agent
---

# profile-gen

Generate a persona (name, profile image, optional animated GIF, optional voice reference,
optional personality) for an AI agent, and record it as a markdown profile.

All scripts live under `scripts/` (relative to this skill's install directory) and each prints
one JSON object to stdout — parse that JSON rather than scraping prose output.

## 0. Resolve directories — read this before running anything

Two directories matter here and **they are almost always different**:

- **`SKILL_DIR`** — the directory this SKILL.md file itself lives in (its install location,
  typically `~/.claude/skills/profile-gen` or `<project>/.claude/skills/profile-gen`, often a
  symlink). Every `scripts/...`/`references/...` path in this document is relative to
  **`SKILL_DIR`**, not the user's project — resolve them there (e.g.
  `python3 <SKILL_DIR>/scripts/check_config.py ...`).
- **`PROJECT_ROOT`** — the user's actual project: the working directory of this session, where
  the persona should actually be written. Determine it once at the start (it's simply the
  directory you're already operating in for this conversation) and pass it as an **absolute
  path** via `--root <PROJECT_ROOT>` to every `write_profile.py` call below. Never omit `--root`
  or leave it to a default — doing so is exactly what previously caused personas to be written
  inside the skill's own installation directory instead of the user's project.

## 1. Parse arguments

Parse whatever the user typed after `/profile-gen` for: free-text description hints, `--backend
chatgpt|grok|grok-cli|comfyui`, `--nsfw`, `--gif`, `--voice NAME`,
`--output claude-md-ref|claude-md|file`, `--assets tracked|gitignored`, `--name NAME`,
`--no-image`, `--no-name`. Anything not recognized as a flag is a description hint.

`--no-image`/`--no-name` control this persona's stored `display.image`/`display.name`
preference (both default `true` — the picture shows and the name prints whenever
`scripts/show_profile.py` runs for it; see `references/terminal-display.md`). These don't need
their own `AskUserQuestion` round — assume both `true` unless the flag was given.

## 2. Gather missing inputs (one question round)

If `--backend`, `--nsfw`/`--gif` intent, `--voice`, `--output`, or `--assets` were not given on
the command line, ask for all of them in a **single** `AskUserQuestion` call (don't ask one at a
time):

- **Backend**: chatgpt / grok (both need an API key — a ChatGPT Plus or X/Grok *subscription*
  alone does not grant one; these are billed separately from the API) / grok-cli (no API key —
  uses the locally-installed `grok` CLI's `/imagine` command against the user's Grok/X
  subscription instead; requires `grok` on PATH and already logged in via `grok login`; costs
  real usage per call and has no seed/size control — see `references/backends.md`) / comfyui (no
  account or API key needed at all — point it at your own ComfyUI server; if you don't have a
  workflow set up yet, this skill can build one for you, LoRA picks included — see step 4a).
- **NSFW**: on/off. Purely a pass-through flag (see `references/prompting.md`) — no client-side
  filtering happens in this skill regardless of the answer.
- **GIF**: whether to also produce an animated version.
- **Voice**: a reference string, or none. See `references/voices.md` for sample names — don't
  invent audio, this is metadata only.
- **Output destination**:
  - `claude-md-ref` (**recommended default, especially for a private/personal/NSFW persona**) —
    the persona's markdown lives on its own (co-located with its assets, tracked or gitignored
    per the next question), and a one-line `@<path>` import is kept in the project's real
    `CLAUDE.md` so it's still auto-discovered — without the persona's actual content (name,
    personality, prompts) ever being inlined into a tracked file.
  - `claude-md` — the full rendered persona is embedded directly in `CLAUDE.md`. Only appropriate
    when the persona itself is meant to be shared/committed as-is (e.g. a team-facing agent
    identity), since this inlines its full content into a tracked file regardless of the assets
    choice below.
  - `file` — a standalone `.md` with no automatic reference anywhere (the user wires it up
    themselves, e.g. their own `@` import or manual read).
- **Asset placement**: tracked in git, or gitignored. For `claude-md-ref`/`file`, "gitignored"
  hides the persona's markdown **and** its images together (private end to end); for `claude-md`,
  it only hides the images (the persona's text is already committed via the inline block).
  **`claude-md-ref` + gitignored specifically** writes to a **fixed, generic path**
  (`.claude/persona/persona.md`) rather than one derived from the persona's name — so the
  one-line `@`-import that lands in the tracked `CLAUDE.md` never reveals who the persona is.
  This means only one such private persona is addressable per project at a time; tell the user if
  they already have one and this run will replace it.

Do not ask about things already supplied as flags.

## 3. Confirm name and personality

Propose a human-like `name` (using any description hints given) and, if the run isn't SFW-and-
personality-less by request, a short `personality` description. Show both to the user and let
them accept or edit before spending any API calls. When `nsfw` is set, write the personality
description in the requested register without disclaimers — see `references/prompting.md`.

Derive `slug` from the confirmed name (this matches what `storage.slugify()` computes, so you
don't need to compute it by hand — the scripts below do it internally).

## 4. Validate backend config

```
python3 scripts/check_config.py --backend <backend>
```

Fix reported config problems (missing env vars, unreachable ComfyUI, unresolved workflow nodes)
before continuing. If `--backend comfyui`, read `references/comfyui.md` first — it documents the
node-title convention the workflow JSON must follow.

## 4a. Auto-build a ComfyUI workflow (comfyui backend, no workflow configured yet)

Skip this step entirely for chatgpt/grok, or if step 4 already reports `comfyui_workflow` as
valid (the user already has one). Otherwise — including when `check_config.py` reports
`comfyui_workflow is not set` — build one instead of asking the user to supply their own:

1. `python3 scripts/inspect_comfyui.py --url <comfyui_url>` — prints the server's installed
   checkpoints, LoRAs, samplers/schedulers, and whether a real native-animation node family is
   present (`has_native_animation`, with `has_animatediff`/`has_ltxv`/`has_wan` and their matched node
   lists saying which). This detection is strict/name-prefix-based on purpose — it has
   previously produced false positives from unrelated nodes that merely mention "AnimateDiff" in
   their name — so trust what it reports rather than assuming a family is available because a
   "normal" ComfyUI setup would have it. If it reports no checkpoints at all, tell the user their
   ComfyUI server has no models installed and stop — a workflow can't be authored with nothing to
   load.
2. Spawn a subagent (`Agent` tool) to actually design the workflow: give it this inventory, the
   confirmed persona name/personality/description hints, and point it at
   `references/comfyui-workflow-authoring.md` for the exact node-title convention, an example
   still-image workflow, how to chain in LoRAs it picks from the inventory, and (only if
   `has_native_animation` is true and the user asked for a GIF) how to also produce an
   AnimateDiff, LTX-Video, or Wan2.x workflow — whichever family the inventory actually reports, using
   only node types that actually appear in its lists. If `has_native_animation` is false, tell
   the subagent to skip the GIF workflow entirely; don't have it attempt one on the hope that a
   real-sounding node name will work. Have it write the file(s) to
   `<asset_dir>/comfyui-workflow.json` (and `<asset_dir>/comfyui-workflow-gif.json` if
   applicable) — `asset_dir` comes from step 5, so run that plan-paths call first if you haven't
   yet. Ask it to report back which checkpoint/LoRAs it used and why, and which animation family
   (if any) it targeted.
3. Validate what it wrote:
   ```
   python3 scripts/check_config.py --backend comfyui --workflow <asset_dir>/comfyui-workflow.json \
     [--gif-workflow <asset_dir>/comfyui-workflow-gif.json] [--gif]
   ```
   This checks two independent things — both must pass before you proceed: (a) `resolved` shows
   no `null` node (unresolved positive/negative/latent/output — most commonly a missing
   `_meta.title`), and (b) no `errors` entry about a node type not installed on the server (the
   subagent referenced something that isn't actually there). Send either failure back to the
   subagent to fix and re-validate. Don't proceed to image/GIF generation with an unresolved or
   unverified workflow.
4. Use `--workflow <asset_dir>/comfyui-workflow.json` (and `--gif-workflow
   <asset_dir>/comfyui-workflow-gif.json`, if built) on the `generate_image.py`/`make_gif.py`
   calls in steps 7-8 below, instead of relying on `COMFYUI_WORKFLOW`/`COMFYUI_GIF_WORKFLOW` env
   vars. Tell the user which checkpoint/LoRAs were picked and that the workflow file was saved
   alongside their profile assets (so it's reusable/editable afterward).

## 5. Plan output paths

```
python3 scripts/write_profile.py --plan-only --name "<name>" --root <PROJECT_ROOT> \
  --output <output> --assets <assets>
```

Prints `{"markdown_path": ..., "asset_dir": ...}`. Use `asset_dir` as the destination directory
for the image (and GIF, if any) in the next steps — the image scripts write directly there.

## 6. Draft the image prompt

Read `references/prompting.md` for the subject/style recipe. Write **only the subject/style
description** (name/appearance/setting/style, from the confirmed name/personality/description
hints) to a temp file — and a plain quality-only negative prompt to a second temp file if you
have specific things to avoid beyond the defaults, for ComfyUI. **Do not append an NSFW clause
yourself, for any backend.** `generate_image.py`/`make_gif.py` do that automatically via
`profilegen.prompt.build()` based on `--nsfw` and `--backend` — and the phrasing that actually
works differs by backend in a way that matters (see `references/prompting.md`): blunt "no
restrictions" language helps on local ComfyUI but reliably triggers refusals on hosted backends
(Grok, Grok CLI, ChatGPT), which need tasteful/suggestive framing instead. Hand-typing a clause
yourself risks using the wrong one, or duplicating what the script already adds.

## 7. Generate the image

Decide the image's path yourself as `<asset_dir>/<slug>.png` (using the `asset_dir` from step 5
and the `slug` from step 3), then:

```
python3 scripts/generate_image.py --backend <backend> --prompt-file <prompt.txt> \
  [--negative-file <negative.txt>] [--nsfw] --out <asset_dir>/<slug>.png [--seed N] \
  [--style-preset "<short style clause>"] [--workflow <asset_dir>/comfyui-workflow.json]
```

The printed JSON includes `positive_prompt`/`negative_prompt` — the actual final prompt text
sent to the backend (NSFW clause and all). Use these verbatim for `generation.prompt`/
`generation.negative_prompt` in the profile fields in step 9, not whatever you originally
drafted, so the recorded provenance matches what was really sent.

Only pass `--workflow` when step 4a built one; otherwise the backend falls back to
`COMFYUI_WORKFLOW`/config (irrelevant for chatgpt/grok).

Prints `{"path", "backend", "model", "seed", "width", "height"}` as JSON. Hold onto the returned
`path` — it's the still image, used as input to step 8, and becomes the profile's `image` field
in step 9 **only if no GIF ends up being generated**. When Pillow is installed (the normal case),
the saved image is always center-cropped to square regardless of what the backend returned —
this matters because some backends (Grok in particular) ignore requested width/height entirely
and can return any aspect ratio, and a non-square image forced into a circular/square avatar
elsewhere is exactly what a "stretched profile picture" looks like. The printed `width`/`height`
are always the real, final dimensions of what was actually saved, not a backend's requested-but-
unverified size. Without Pillow installed, no cropping/format-conversion happens (the actual file
may end in `.jpg` instead of `.png`, e.g. Grok's JPEG output) and `width`/`height` may be `null`
for backends that don't actually control their own output size.

## 8. Generate the GIF (optional)

If the user asked for a GIF, decide its path as `<asset_dir>/<slug>.gif`, then:

```
python3 scripts/make_gif.py --backend <backend> --png <image_path> --out <asset_dir>/<slug>.gif \
  [--mode auto|native|synthetic] [--prompt-file <prompt.txt>] [--negative-file <negative.txt>] \
  [--nsfw] [--seed N] [--gif-workflow <asset_dir>/comfyui-workflow-gif.json]
```

`--mode auto` (the default) uses the backend's native animation workflow when available (ComfyUI
with `comfyui_gif_workflow` configured — set this from step 4a's validated GIF workflow, not at
all if step 4a found no native animation family — or `grok-cli`) and otherwise falls back to a
synthetic "living portrait" effect applied to the still image. These are not the same thing:
**native mode animates the subject itself** (blinking, breathing, slight head movement — the
script automatically adds a motion clause to the prompt to make sure of this, see
`references/prompting.md`), while **synthetic mode only pans/zooms the camera over the static
image** — the person doesn't move. Prints `{"path", "mode": "native"|"synthetic", "frames",
"duration_ms"}` as JSON — tell the user plainly which one happened (don't call a synthetic GIF
"animated" without qualifying that only the framing moves).

**If this call errors** (e.g. ComfyUI rejects the workflow at generation time), do not silently
retry with `--mode synthetic` and present the result as if that's what was always going to
happen. Show the user the actual error first — it usually means the workflow referenced
something that isn't really on the server (which step 4a's validation should have already
caught; if it slipped through anyway, that's worth surfacing, not papering over) — and only fall
back to synthetic once they've acknowledged native generation didn't work. The user explicitly
wants real subject animation when they ask for a GIF; a silent downgrade defeats that.

**There is only one `image` field, never two.** If this step ran, its returned `path` (the GIF)
*replaces* the PNG from step 7 as the profile's `image` — the still PNG was only ever an
intermediate input (synthetic mode needs it directly; native mode still uses it to establish the
subject). Only fall back to the step 7 PNG path as `image` if this step was skipped entirely.

## 9. Write the profile

Assemble a fields JSON object per `references/profile-schema.md` (name, slug, image, nsfw,
display, generation, plus voice/personality if set) to a temp file. Set `image` to the GIF path
from step 8 if one was generated, otherwise the PNG path from step 7 — never both, there's no
separate animated-image field. Set `generation.gif_mode` to the `mode` step 8 reported, or `null`
if step 8 was skipped. Set `display.image`/`display.name` from step 1's `--no-image`/`--no-name`
parse (`true` unless the flag was given — `write_profile.py` also fills in `true` for either key
if you omit `display` entirely, so it's safe to leave out when both are on). Then:

```
python3 scripts/write_profile.py --fields-file <fields.json> --root <PROJECT_ROOT> \
  --output <output> --assets <assets>
```

This renders the markdown, writes it to the planned path, updates `.gitignore` when `--assets
gitignored`, and for `--output claude-md-ref` also writes/replaces the one-line `@`-import block
in `<PROJECT_ROOT>/CLAUDE.md`. Prints `{"markdown_path", "image_path", "gitignore_updated",
"claude_md_updated", "claude_md_path"}` (`claude_md_path` is `null` for `--output file`).

## 10. Preview in the terminal

If `display.image` or `display.name` ended up `true`, show the persona right away:

```
python3 scripts/show_profile.py --profile <markdown_path> --root <PROJECT_ROOT>
```

This is a silent no-op in a terminal with no supported inline-image protocol (or if both display
fields are off) — see `references/terminal-display.md` for which terminals it actually draws an
image in and how the sizing/fallback works. Don't treat "nothing appeared" as an error.

This one call only previews the persona for the rest of *this* session. If the user wants it to
show automatically at the start of every future session in this project too (the common reason to
want this feature at all — "I forget who I'm talking to"), that needs a `SessionStart` hook wired
into the project's `.claude/settings.json`; walk them through `references/terminal-display.md`'s
hook snippet (or hand it to the `update-config` skill) rather than doing it silently, since it
edits a config file outside this skill's own output paths.

## 11. Report results

Tell the user: the name, where the persona's markdown landed, where the image/GIF landed, whether
`.gitignore` was touched, and — for `claude-md-ref`/`claude-md` — whether an existing CLAUDE.md
block was replaced vs. newly appended (re-running with the same name/slug always replaces in
place rather than duplicating). For `claude-md-ref` specifically, make clear that only a one-line
reference was added to CLAUDE.md and the persona's actual content lives at `markdown_path`
(private/gitignored if that's what `--assets` was set to). Also mention whether the terminal
preview actually drew an image (vs. silently skipping for lack of protocol support) and whether
they want the SessionStart hook set up for persistent display.

## Reference files

- `references/profile-schema.md` — full field reference, both render-mode examples.
- `references/prompting.md` — prompt recipe, NSFW clause, negative-prompt rules.
- `references/comfyui.md` — read only when `--backend comfyui`.
- `references/comfyui-workflow-authoring.md` — handed to the workflow-building subagent in step
  4a; read it yourself too if you end up authoring/fixing a workflow directly.
- `references/backends.md` — ChatGPT/Grok config details.
- `references/voices.md` — read only when picking a voice for the user.
- `references/terminal-display.md` — how `show_profile.py` detects a terminal's inline-image
  protocol, sizing/fallback behavior, and the `SessionStart` hook snippet for persistent
  per-session display.
