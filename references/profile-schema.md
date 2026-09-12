# Profile schema reference

Canonical definition: `assets/profile.schema.json`. This document explains each field in
plain language and shows one example of each render mode.

## Fields

| Field | Required | Type | Notes |
|---|---|---|---|
| `schema_version` | yes | `1` (const) | Bump only if the schema shape changes. |
| `name` | yes | string | Human-readable display name, e.g. `"Ada Sterling"`. |
| `slug` | yes | string | `^[a-z0-9]+(-[a-z0-9]+)*$` — derived from `name` via `storage.slugify()`. Used in file/dir names and as the CLAUDE.md marker-block key. |
| `image` | yes | string (path) | Path to the profile's single picture, relative to the repo root — a static PNG, or an animated GIF if one was generated (see `generation.gif_mode`). There is only ever one image field; a GIF replaces the PNG here rather than sitting alongside it. |
| `voice` | no | string or `null` | Opaque voice-name reference (e.g. a Kokoro TTS voice like `af_jessica`). Metadata only — no audio is synthesized. See `references/voices.md`. |
| `personality` | no | string or `null` | Free-form prose description of the persona's personality/register. |
| `nsfw` | yes | boolean | Whether this profile was generated in NSFW mode. Threads through to `generation.prompt`/`generation.negative_prompt` and the backend call — see `references/prompting.md`. |
| `display` | yes | object | Whether `scripts/show_profile.py` shows this persona's picture/name inline in the terminal. See below. |
| `generation` | yes | object | Provenance of how the image was produced. See below. |

### `display` object

| Field | Required | Type | Notes |
|---|---|---|---|
| `image` | yes | boolean | Show the profile picture inline in a supporting terminal (iTerm2/WezTerm, Kitty, or sixel via `img2sixel`) when `show_profile.py` runs. Set at generation time via `--show-image`/`--no-image`; `true` by default. |
| `name` | yes | boolean | Print the persona's name when `show_profile.py` runs. Set via `--show-name`/`--no-name`; `true` by default. |
| `autostart` | yes | boolean | Whether a `SessionStart` hook shows this persona *on its own*. Separate from `image`/`name`, which say what gets drawn once it is shown — `autostart: false` keeps a persona fully available via `/display-profile` while stopping it appearing unprompted. Only consulted under `show_profile.py --autostart-only` (what the hook passes); `true` by default. |

Written by every profile-gen run from this point forward. A profile written before this field
existed simply lacks it — `show_profile.py` treats a missing `display` (or a missing `image`/
`name` key within it) as `true`, so older profiles keep behaving as if both were on. See
`references/terminal-display.md` for how `show_profile.py` uses this.

### `generation` object

| Field | Required | Type | Notes |
|---|---|---|---|
| `backend` | yes | `"chatgpt"` \| `"grok"` \| `"grok-cli"` \| `"comfyui"` \| `"mock"` | Which backend produced the image. |
| `model` | yes | string | Backend-reported model identifier (e.g. `gpt-image-1`, `grok-2-image`). |
| `prompt` | yes | string | Final positive prompt sent to the backend (including the NSFW clause, if any). |
| `negative_prompt` | no | string or `null` | Final negative prompt, if the backend supports one (ComfyUI). `null` for backends without a negative-prompt concept. |
| `seed` | yes | integer or `null` | Seed used for the generation, when known. |
| `gif_mode` | yes | `"native"` \| `"synthetic"` \| `null` | Whether `image` is an animated GIF and how it was produced, or `null` when `image` is a plain static PNG. |
| `created_at` | yes | string (ISO 8601 date-time) | When the profile was generated. |

A GIF-based profile looks identical except `image` ends in `.gif` and `gif_mode` is
`"native"`/`"synthetic"` instead of `null` — e.g. `image: "profiles/ada-sterling/ada-sterling.gif"`,
`gif_mode: "synthetic"`. There's never a separate animated-image field to also populate.

## Example: standalone file

Rendered by `templates/profile.standalone.md.j2` via `render.render_standalone()`. See
`assets/example-profile/example-profile.md` for a full committed sample.

```markdown
---
schema_version: 1
name: "Ada Sterling"
slug: "ada-sterling"
image: "assets/example-profile/example-profile.png"
voice: "af_jessica"
nsfw: false
display:
  image: true
  name: true
  autostart: true
generation:
  backend: "mock"
  model: "mock-v1"
  prompt: "portrait of a calm, precise engineer"
  negative_prompt: blurry, low quality
  seed: 42
  gif_mode: null
  created_at: "2026-09-10T00:00:00Z"
---

# Ada Sterling

![Ada Sterling](assets/example-profile/example-profile.png)

## Personality

Warm, precise, and a little wry.
```

## Example: `claude-md-ref` (recommended for private/NSFW personas)

**Tracked (`--assets tracked`)**: the persona's markdown is stored exactly like the
standalone-file example above (co-located with its assets, slug-named, visible in the repo), and
`storage.write_claude_md_reference()` keeps a one-line import in `CLAUDE.md`:

```markdown
<!-- profile-gen:start slug=ada-sterling -->
@profiles/ada-sterling/ada-sterling.md
<!-- profile-gen:end slug=ada-sterling -->
```

**Gitignored (`--assets gitignored`)** — the private/NSFW case: the persona lives at a **fixed,
generic path** instead, `.claude/persona/persona.md`, never derived from its name, so the tracked
reference can't reveal identity either:

```markdown
<!-- profile-gen:start slug=persona -->
@.claude/persona/persona.md
<!-- profile-gen:end slug=persona -->
```

`@<path>` is Claude Code's own file-import syntax — anyone opening the project gets the persona
loaded automatically, without any of its content (name, personality, prompts, NSFW flag) ever
being inlined into a tracked file, and in the gitignored case not even its *name* appears in the
tracked reference. Re-running with the same slug/fixed-key replaces this reference block in
place. This mirrors a common hand-rolled pattern (e.g. a project's `CLAUDE.md` importing a fixed
`@.claude/PERSONA.md`) but scopes `.gitignore` narrowly to `.claude/persona/` instead of
blanket-ignoring all of `.claude/`. The trade-off of the fixed path: only one gitignored persona
is addressable this way per project at a time.

## Example: fully embedded in CLAUDE.md (`--output claude-md`)

Rendered by `templates/profile.embedded.md.j2` via `render.render_embedded()` and inserted/
replaced in place by `storage.write_markdown_output(..., output="claude-md", ...)`. Use this only
when the persona itself is meant to be shared/committed as-is — its full content lands in a
tracked file regardless of the `--assets` choice.

```markdown
<!-- profile-gen:start slug=ada-sterling -->
### Ada Sterling

![Ada Sterling](assets/example-profile/example-profile.png)

\`\`\`yaml
schema_version: 1
name: "Ada Sterling"
slug: "ada-sterling"
image: "assets/example-profile/example-profile.png"
voice: "af_jessica"
nsfw: false
display:
  image: true
  name: true
  autostart: true
generation:
  backend: "mock"
  model: "mock-v1"
  prompt: "portrait of a calm, precise engineer"
  negative_prompt: blurry, low quality
  seed: 42
  gif_mode: null
  created_at: "2026-09-10T00:00:00Z"
\`\`\`

**Personality:** Warm, precise, and a little wry.
<!-- profile-gen:end slug=ada-sterling -->
```

Re-running profile-gen with the same `slug` replaces this block in place rather than
duplicating it — see `storage.write_markdown_output()`.
