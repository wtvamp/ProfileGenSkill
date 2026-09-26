# profile-gen

A Claude Code skill that generates a persona for an AI agent — a profile image (with an optional
animated GIF), a human-like name, an optional voice reference, and an optional personality
description — and records it as a standalone markdown profile, auto-discoverable via a one-line
`@`-import kept in `CLAUDE.md` (or, optionally, fully inlined into `CLAUDE.md` instead). A private
or NSFW persona can be kept entirely out of git this way — see "Output and asset placement" below.

## Install

Copy (or symlink) this repo into a skills directory Claude Code will discover:

```bash
# project-scoped (this repo only)
mkdir -p .claude/skills
ln -s "$(pwd)" .claude/skills/profile-gen

# or user-scoped (available in every project)
mkdir -p ~/.claude/skills
ln -s "$(pwd)" ~/.claude/skills/profile-gen

# the /display-profile companion command (switch variants, show/hide the picture)
mkdir -p ~/.claude/commands
ln -s "$(pwd)/commands/display-profile.md" ~/.claude/commands/display-profile.md
```

If you run Claude Code with `CLAUDE_CONFIG_DIR` set, link into that directory's `skills/` and `commands/` instead of (or as well as) `~/.claude`.

Then invoke it from Claude Code as `/profile-gen`, and `/display-profile` to control how a generated persona is shown.

## Requirements

- Python 3.10+
- `pytest` and `PyYAML` (dev/test only — see `requirements.txt`). The runtime scripts under
  `scripts/` use only the standard library plus, optionally, Pillow for GIF assembly/JPEG
  normalization (guarded with `try/except ImportError`; features degrade gracefully without it).

## Backend configuration

Pick one backend per run with `--backend chatgpt|grok|grok-cli|comfyui|mock`. Config is resolved
in this order: CLI flag > environment variable > `./.claude/profile-gen.json` >
`~/.claude/profile-gen.json`.

| Backend | Required config | Notes |
|---|---|---|
| `chatgpt` | `OPENAI_API_KEY` | OpenAI Images API, `gpt-image-1` by default. **Needs an API key specifically** — a ChatGPT Plus/Pro subscription does not include one; API access is billed separately at platform.openai.com. |
| `grok` | `XAI_API_KEY` | xAI Images API, `grok-2-image` by default. Returns JPEG, normalized to PNG via Pillow when available. **Needs an API key specifically** — an X Premium+/SuperGrok subscription does not include one; API access is billed separately at console.x.ai. |
| `grok-cli` | none (just the `grok` CLI installed + `grok login` done once) | No API key — shells out to the locally-installed `grok` CLI's `/imagine`/`/imagine-video` slash commands, billed against the user's existing Grok/X subscription usage instead. No seed/size control, costs real usage per call, and the Grok agent may apply its own judgment to the request. See `references/backends.md`. |
| `comfyui` | `COMFYUI_URL`, optionally `COMFYUI_WORKFLOW` | No account, subscription, or API key needed — just your own (or a friend's/rented) ComfyUI server. **Don't have a workflow JSON?** Leave `COMFYUI_WORKFLOW` unset and the skill will build one for you (see below) — no config beyond the server URL is required to get started. |
| `mock` | none | No network calls; draws a placeholder PNG. Useful for offline testing — see `references/prompting.md` / `tests/`. |

Run `python3 scripts/check_config.py --backend <name>` to validate config before generating
anything — for ComfyUI this also dry-runs node resolution and reports which node IDs it found.

### ComfyUI without a pre-built workflow

If you don't have an API key for ChatGPT/Grok (subscriptions to those products don't grant one)
and just want something that works with no account at all, ComfyUI is the path — and you don't
need to hand-build a workflow first. Point `COMFYUI_URL` at your server, leave `COMFYUI_WORKFLOW`
unset, and the skill will:

1. Query your server's installed checkpoints/LoRAs/samplers via `scripts/inspect_comfyui.py`.
2. Hand that inventory to a subagent that authors an API-format workflow JSON following the
   convention in `references/comfyui-workflow-authoring.md`, picking LoRAs from what's actually
   installed on your server (never invented).
3. Validate the result with `scripts/check_config.py --backend comfyui --workflow <path>` before
   generating anything, saving the workflow file alongside your profile's assets so it's reusable
   and editable afterward.

See `references/comfyui.md` for the node-title convention the (auto- or hand-built) workflow
follows, and pass `--workflow`/`--gif-workflow` to `generate_image.py`/`check_config.py`/
`make_gif.py` to point at a specific file without touching `COMFYUI_WORKFLOW`/`COMFYUI_GIF_WORKFLOW`.

## Terminal display

`scripts/show_profile.py` shows a persona's picture and/or name inline in the terminal — iTerm2/WezTerm, Kitty/Ghostty, and sixel (via `img2sixel`) are all supported, sized to roughly 10% of the terminal's width, with a silent no-op in a terminal that supports none of those. `--no-image`/`--no-name` at generation time turn either off per-persona (both default on). See `references/terminal-display.md` for protocol/sizing details and a `SessionStart` hook snippet that shows a project's persona automatically at the start of every future session, not just right after generating it.

## SFW and NSFW pictures

Every persona has a **SFW picture**. `--nsfw` adds a second, optional **NSFW picture**
(`image_nsfw`) of the same character — same backend, same seed, same base prompt, regenerated
with the NSFW clause appended — rather than making the persona's one picture explicit.

Which of the two is on screen is the persona's `display.variant`, and it starts at `sfw`:

```
/display-profile nsfw on       # show the NSFW picture
/display-profile nsfw off      # back to the SFW one
/display-profile nsfw toggle   # flip to whichever isn't showing
```

A switch rewrites the profile's own `image:` and its body picture to the selected file (both variants stay recorded, as `image_sfw` and `image_nsfw`). So anything else that reads the profile as a plain markdown file with a picture — Claude Buddy, for one — shows the selected picture without knowing variants exist.

The switch is persisted in the profile's own markdown, so it survives across sessions until
switched back, and it touches nothing else about the persona. The NSFW picture is referenced
from the profile's frontmatter only — the markdown body's visible image is always the SFW one,
so an explicit picture never gets inlined into a tracked `CLAUDE.md`.

The NSFW clause itself is a pure pass-through: it's forwarded unmodified to whichever backend
you picked (plus a `moderation: "low"` request param, ChatGPT only), and it shapes the
personality description Claude writes. No client-side filtering is layered on top in either
direction — see `references/prompting.md`.

A profile written before this existed (one `image`, `nsfw: true`) still works: its single
picture is treated as the NSFW variant, and it displays exactly as it always did.

## Output and asset placement

`--root` is **required** on every `write_profile.py` call and must be an absolute path to your
actual project — never the skill's own installation directory. `write_profile.py`'s own scripts
live wherever the skill is installed (e.g. `~/.claude/skills/profile-gen`); the persona itself
should land in your project, which is why `--root` is never defaulted.

Two independent choices then decide the layout, per run: `--output claude-md-ref|claude-md|file`
and `--assets tracked|gitignored`.

| `--output` | `--assets` | markdown | asset dir |
|---|---|---|---|
| `file` | `tracked` | `profiles/<slug>/<slug>.md` | `profiles/<slug>/` |
| `file` | `gitignored` | `.profiles-assets/<slug>/<slug>.md` | `.profiles-assets/<slug>/` |
| `claude-md-ref` | `tracked` | `profiles/<slug>/<slug>.md` + `@`-ref in `CLAUDE.md` | `profiles/<slug>/` |
| `claude-md-ref` | `gitignored` | `.claude/persona/persona.md` + `@`-ref in `CLAUDE.md` | `.claude/persona/` |
| `claude-md` | `tracked` | full block in `./CLAUDE.md` | `profiles/<slug>/` |
| `claude-md` | `gitignored` | full block in `./CLAUDE.md` | `.profiles-assets/<slug>/` |

**`claude-md-ref` (the default) is the recommended choice for a private or NSFW persona**: with
`--assets gitignored`, the persona's markdown *and* its images are both excluded from git, while
`CLAUDE.md` keeps a one-line `@.claude/persona/persona.md` import (Claude Code's own file-import
syntax) so the persona is still auto-loaded for anyone opening the project. That path is
**fixed and generic** — it never contains the persona's actual name, so nothing about who they
are is visible in the tracked `CLAUDE.md`, matching a common hand-rolled pattern (a project's
`CLAUDE.md` importing a fixed `@.claude/PERSONA.md`). The trade-off: only **one** private
persona is addressable this way per project at a time — regenerating with a different name
overwrites the previous one at that same fixed path. For multiple simultaneous personas, use
`--assets tracked` (visible, slug-named, any number of them) instead. `claude-md` (no `-ref`)
inlines the whole persona into `CLAUDE.md` directly — only use that when the persona is meant to
be shared/committed as-is.

Re-running with the same name/slug replaces the existing block/file in place instead of
duplicating it. See `references/profile-schema.md` for the full field reference and one example
of each render mode, and `assets/example-profile/` for a committed sample.

## Example invocations

```
/profile-gen a calm, precise systems engineer --backend chatgpt --voice af_jessica
/profile-gen --name "Rho" --backend mock --gif --output file --assets gitignored
/profile-gen --backend comfyui --nsfw --output claude-md-ref --assets gitignored
/profile-gen --backend grok-cli --output claude-md --assets tracked
```

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m pytest tests/
```

Run individual scripts directly, e.g.:

```bash
python3 scripts/write_profile.py --plan-only --name "Ada Sterling" --root "$(pwd)" \
  --output file --assets tracked
```

Each script prints one JSON object to stdout (`{"error": "..."}` with a nonzero exit on failure)
so it's easy to script against or parse from `SKILL.md`'s instructions.
