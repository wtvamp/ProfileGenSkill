# Terminal display reference

`scripts/show_profile.py` shows a persona's picture and/or name inline in the terminal, using whatever inline-image mechanism the current terminal actually supports. It never errors out over an unsupported terminal or a missing persona — a preview failing to show is not worth interrupting a session over, especially when it's meant to run unattended from a hook.

## What gets shown, and when

Each persona's `display.image`/`display.name` fields (see `references/profile-schema.md`) control this — set at generation time via `--show-image`/`--no-image`/`--show-name`/`--no-name`, defaulting to `true`/`true`. A profile written before this field existed is treated as `true`/`true` too.

Two invocation modes:

- `--profile <markdown_path> --root <PROJECT_ROOT>` — shows exactly one profile, used right after `write_profile.py` for an immediate preview (SKILL.md step 10).
- `--root <PROJECT_ROOT>` (no `--profile`) — discovers every persona currently auto-loaded via `<PROJECT_ROOT>/CLAUDE.md`'s `profile-gen` marker blocks and shows each one. This is the mode for a `SessionStart` hook (below), since it needs no argument beyond the project root to find whatever persona(s) are active in that project.

`--show-image`/`--no-image`/`--show-name`/`--no-name` on the command line override a persona's stored preference for that one invocation only, without touching what's saved in its markdown.

## Terminal protocol detection

`scripts/profilegen/termimg.py` picks a protocol from environment variables — there's no safe way to probe a terminal's real capability without risking corrupting its state, so this errs toward silently doing nothing over guessing wrong:

| Terminal | Detected via | Mechanism |
|---|---|---|
| iTerm2 | `$TERM_PROGRAM == "iTerm.app"` | Native inline-image protocol (OSC 1337) — the same one the `imgcat` utility uses. |
| WezTerm | `$TERM_PROGRAM == "WezTerm"` | Implements iTerm2's protocol, so it's handled identically. |
| Kitty / Ghostty | `$KITTY_WINDOW_ID` set, or `$TERM == "xterm-kitty"` | Prefers shelling out to `kitten icat`/`icat` if on `PATH` (handles GIF animation and chunking correctly); falls back to the raw Kitty graphics protocol for static PNGs only if neither binary is available. |
| Anything with `img2sixel` installed | `shutil.which("img2sixel")` | Sixel, as a last resort. |
| Everything else (plain Terminal.app, VS Code's integrated terminal, a bare SSH session, etc.) | none of the above matched | No image is drawn. The name still prints as plain text if `display.name` is on — that part works everywhere. |

## Sizing

"10% of the terminal window" (the default `--width-pct`) means different things per protocol:

- **iTerm2/WezTerm**: exact. The protocol has a native percentage-width parameter, so the terminal itself computes it against its real pixel dimensions.
- **Kitty (raw protocol path)**: approximated in character cells — `terminal_columns * width_pct / 100`, with the row count set to half that (most monospace fonts render cells roughly twice as tall as wide, so halving keeps a square profile picture looking square instead of stretched). Not pixel-exact.
- **Sixel**: approximated at roughly 8px per terminal column, since `img2sixel` wants a pixel width and there's no portable way to query a terminal's exact cell size outside iTerm2/Kitty-specific escape queries this module doesn't attempt.

## Animated (GIF) personas

iTerm2/WezTerm animate a GIF natively — no special handling needed, the raw bytes go straight through. Kitty only animates via the `kitten icat`/`icat` helper; if neither is on `PATH`, a GIF persona is silently skipped on Kitty rather than shown as a broken or static first frame. Sixel doesn't animate at all here.

## tmux

Both iTerm2 and Kitty sequences get wrapped in tmux's passthrough escape (`\ePtmux; ... \e\\`) whenever `$TMUX` is set. This requires `set -g allow-passthrough on` in the user's tmux config — tmux blocks passthrough by default and there's no way to detect that setting from here, so a silently-blocked image inside tmux most likely means that line is missing.

## Wiring persistent display via a SessionStart hook

`show_profile.py --profile ...` (SKILL.md step 10) only previews a persona for the rest of the session it was just generated in. To have a persona show automatically at the start of *every* future session in a project — the point of this feature, since the whole reason to want it is "I forget who I'm talking to" — add a `SessionStart` hook to the project's `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 <SKILL_DIR>/scripts/show_profile.py --root \"$CLAUDE_PROJECT_DIR\""
          }
        ]
      }
    ]
  }
}
```

Replace `<SKILL_DIR>` with this skill's actual install location (e.g. `~/.claude/skills/profile-gen` — the same directory this file lives under). `$CLAUDE_PROJECT_DIR` is the project-root environment variable Claude Code sets for hook commands; if a given Claude Code version doesn't set it, hardcode the project's absolute path instead of relying on a default.

This hook needs no `--profile` argument — plain `--root` mode discovers whichever persona(s) are referenced from that project's `CLAUDE.md` on its own. Use the `update-config` skill to actually apply a settings.json change like this one, rather than hand-editing it.
