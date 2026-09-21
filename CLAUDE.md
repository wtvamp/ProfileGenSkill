# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This repository holds a Claude Code **skill** for generating agent personas: a profile image (via ChatGPT, Grok, Grok CLI, or a self-hosted ComfyUI server, with an optional animated GIF), a human-like name, an optional voice reference, and an optional personality description. Each persona has a SFW picture and optionally an NSFW one — the same character from the same seed and base prompt — and `/display-profile nsfw on|off|toggle` switches which of them is on screen. The generated profile can be attached directly into `CLAUDE.md`, kept as a one-line auto-discoverable `@`-import pointing at a separate `.md` file, or written as a fully standalone file with no automatic reference at all — and that external file/its images can be tracked in git or kept in a `.gitignore`'d location, so a private or NSFW persona never has to touch a tracked file.

## Current state

The skill is implemented. Entry point: `SKILL.md` (frontmatter + step-by-step instructions for Claude to follow when `/profile-gen` is invoked). Supporting code lives under `scripts/`:

- `scripts/profilegen/` — the reusable package:
  - `backends/` — `ImageBackend` protocol (`base.py`) plus `chatgpt.py`/`grok.py`/`grok_cli.py`/`comfyui.py`/`mock.py` implementations.
  - `config.py` — backend config resolution (CLI flag > env var > project config > user config).
  - `prompt.py` — NSFW-aware prompt building, shared across backends.
  - `variants.py` — which of a persona's two pictures (`image` / `image_nsfw`) `display.variant` selects, plus the reinterpretation that keeps pre-variant profiles working.
  - `gif.py` — synthetic "living portrait" GIF assembly (pan/zoom fallback when no native animation backend is available).
  - `comfyui_inventory.py` — parses a ComfyUI server's `/object_info` into checkpoints/LoRAs/samplers and native-animation-family detection.
  - `render.py` — mini regex-based template engine for `templates/*.j2` (no Jinja dependency; see its module docstring for the supported `{{ field }}` / `{% if field %}...{% endif %}` syntax).
  - `frontmatter.py` — the read-side counterpart to `render.py`: a small dependency-free parser for profile-gen's own generated markdown (frontmatter block, CLAUDE.md marker blocks, embedded fenced-YAML), plus `block_span()`/`set_display_flags()` for editing a persona's `display:` block in place without touching anything else in the file.
  - `discovery.py` — shared "find every persona referenced from this project's CLAUDE.md" logic used by both `show_profile.py` and `toggle_display.py`.
  - `hud.py` + `scripts/hud/PersonaHUD.swift` (macOS) / `scripts/hud/persona_hud.py` (Windows) — **the default display path**: a small always-on-top, click-through badge floating over the terminal window — the persona's picture as a rounded-square tile (animated, for a GIF) with their name beside it on a dark card, at the top centre of the pane by default (`--position` can move it to a corner or the middle instead). It consumes no terminal rows, touches no user configuration, and depends on no terminal image protocol, so tmux is irrelevant to it. Two platform implementations behind one interface, selected by `hud.py`: Swift/AppKit `NSPanel` on macOS (compiled on first use into `~/.cache/profile-gen`), tkinter + `ctypes` on Windows (a script, nothing to build — untested on real hardware as of writing). Pid files are per tmux pane so personas in different sessions stay independent, and the overlay asks tmux whether its own window is on screen before showing.
  - `termstate.py` — opt-in `--mode state` only: iTerm2 badge (persona name) + background image (persona picture). Survives tmux, but it overwrites *user-owned* iTerm2 settings, so it is never auto-selected. Also resolves the active tmux pane's tty device so escape sequences still reach the user's screen when invoked from a context whose stdout is captured rather than attached to a terminal (an agent's shell tool).
  - `termimg.py` — inline-image display (iTerm2/WezTerm, Kitty/Ghostty, sixel), painted into the text grid at ~10% of terminal width. Used by `--mode inline`; degrades to a clipped sliver under tmux, which is why the overlay is the default instead.
  - `storage.py` — path policy, slugify, idempotent `.gitignore`/`CLAUDE.md` block edits.
  - `http.py` — thin urllib wrapper used by the hosted backends.
- CLI entry points, each printing one JSON object to stdout: `scripts/check_config.py`, `scripts/inspect_comfyui.py`, `scripts/generate_image.py`, `scripts/make_gif.py`, `scripts/write_profile.py`, `scripts/toggle_display.py`, `scripts/show_profile.py` (the last one is the exception — it writes terminal escape sequences to the user's terminal, and only prints its JSON report when stdout isn't a tty, i.e. when a program rather than a human is reading it).
- `~/.claude/commands/display-profile.md` — the `/display-profile` user command wrapping `show_profile.py`/`toggle_display.py` for interactive on/off control and previewing (lives outside this repo, in the user's own Claude Code config, since it's a lightweight command rather than a second skill).
- `templates/*.j2` — the standalone and CLAUDE.md-embedded markdown templates rendered by `render.py`. The body's visible `![name](...)` is always the SFW picture; the NSFW one is referenced from the frontmatter only, so it never lands inline in a tracked CLAUDE.md.
- `references/*.md` — progressive-disclosure docs `SKILL.md` points Claude to on demand: `profile-schema.md`, `prompting.md`, `comfyui.md`, `comfyui-workflow-authoring.md`, `backends.md`, `voices.md`, `terminal-display.md` (protocol/sizing details and the `SessionStart` hook snippet for automatic per-session persona display).
- `assets/profile.schema.json` — the profile JSON Schema; `assets/example-profile/` — one committed sample standalone output.
- `tests/` — pytest suite (20 files) covering prompt/NSFW logic, ComfyUI node resolution and inventory parsing, template rendering + frontmatter round-tripping, terminal-image protocol detection, iTerm2 badge/background state + pane-tty resolution, HUD overlay build/launch/per-pane isolation, display-flag toggling (including `autostart`, the `sfw`/`nsfw` variant switch and its refusal when the requested picture doesn't exist, and appending a flag to a profile that predates it), variant resolution and legacy-profile reinterpretation, storage path policy, the mock-backend end-to-end pipeline, and Grok/Grok-CLI backend behavior.

See `README.md` for install and backend-config instructions.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # pytest, PyYAML (dev-only)
python3 -m pytest tests/
```

Scripts are runnable directly without going through Claude, e.g.:

```bash
python3 scripts/write_profile.py --plan-only --name "Ada Sterling" --root "$(pwd)" --output file --assets tracked
python3 scripts/check_config.py --backend mock
python3 scripts/show_profile.py --root "$(pwd)"
```

`--root` is required on every `write_profile.py` call (and meaningful, though defaulted to `.`, on `show_profile.py`) — it must be the target project's actual directory, never this skill's own installation directory; see the module docstrings for why.

`PyYAML` and `Pillow` are optional at runtime (guarded with `try/except ImportError`); only `pytest` and `PyYAML` are needed to run the test suite in full (a couple of YAML-parsing assertions in `tests/test_render.py` skip gracefully if PyYAML isn't installed). `show_profile.py`'s Kitty/sixel paths additionally shell out to `kitten`/`icat`/`img2sixel` when present on `PATH`, but degrade gracefully (falling back to the raw protocol, or skipping the image entirely) when they aren't.

<!-- profile-gen:start slug=persona -->
@.claude/persona/persona.md
<!-- profile-gen:end slug=persona -->
