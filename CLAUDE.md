# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This repository is empty and has no code, build tooling, or tests yet. It is intended to hold a
Claude Code **skill** for generating agent profiles/personas. Based on the goal stated when this
repo was initialized, the skill should let an agent generate a persona consisting of:

- A profile image representing the agent (generated via ChatGPT or Grok if one isn't already
  supplied)
- A human-like name
- An optional voice
- An optional personality description

The skill should support attaching the generated profile either directly into `CLAUDE.md` or into
a separate external `.md` file, and that external file should optionally be checked into git or
placed in a `.gitignore`'d location.

## Current state

The skill is implemented. Entry point: `SKILL.md` (frontmatter + step-by-step instructions for
Claude to follow when `/profile-gen` is invoked). Supporting code lives under `scripts/`:

- `scripts/profilegen/` — the reusable package: `backends/` (ChatGPT/Grok/ComfyUI/mock, behind
  the `ImageBackend` protocol in `backends/base.py`), `config.py` (config precedence), `prompt.py`
  (NSFW-aware prompt building), `gif.py` (synthetic GIF assembly), `render.py` (mini
  regex-based template engine — no Jinja dependency, see its module docstring for the supported
  `{{ field }}` / `{% if field %}...{% endif %}` syntax), `storage.py` (path policy, slugify,
  idempotent `.gitignore`/`CLAUDE.md` block edits), `http.py` (thin urllib wrapper).
- `scripts/check_config.py`, `generate_image.py`, `make_gif.py`, `write_profile.py` — CLI entry
  points, each printing one JSON object to stdout.
- `templates/*.j2` — the standalone and CLAUDE.md-embedded markdown templates rendered by
  `render.py`.
- `references/*.md` — progressive-disclosure docs `SKILL.md` points Claude to on demand
  (profile schema, prompting/NSFW recipe, ComfyUI workflow convention, backend config, voices).
- `assets/profile.schema.json` — the profile JSON Schema; `assets/example-profile/` — one
  committed sample standalone output.
- `tests/` — pytest suite covering prompt/NSFW logic, ComfyUI node resolution, template
  rendering, and all four output/assets path combinations.

See `README.md` for install and backend-config instructions.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # pytest, PyYAML (dev-only)
python3 -m pytest tests/
```

Scripts are runnable directly without going through Claude, e.g.:

```bash
python3 scripts/write_profile.py --plan-only --name "Ada Sterling" --output file --assets tracked
python3 scripts/check_config.py --backend mock
```

`PyYAML` and `Pillow` are optional at runtime (guarded with `try/except ImportError`); only
`pytest` and `PyYAML` are needed to run the test suite in full (a couple of YAML-parsing
assertions in `tests/test_render.py` skip gracefully if PyYAML isn't installed).
