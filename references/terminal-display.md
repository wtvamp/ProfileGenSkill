# Terminal display reference

`scripts/show_profile.py` shows a persona's picture and/or name in the user's terminal. It never errors out over an unsupported terminal or a missing persona — a persona failing to display is not worth interrupting a session over, especially when it's meant to run unattended from a hook.

## The two problems, and why the overlay is the default

**tmux only tracks text cells.** An inline image is painted into the terminal's text grid. tmux forwards the image bytes once (that's all `allow-passthrough` buys you) and then has nothing in its model to redraw, so the image is lost on the next repaint — in practice a clipped sliver. Measured on iTerm2 3.6.11 + tmux 3.7b: inline images fail under tmux, while iTerm2's badge and background image work (they're session state rendered outside the grid). Sixel would be the one in-grid protocol tmux can natively track, but it isn't compiled into stock iTerm2 builds. The conclusion is that no *in-terminal* image channel is both reliable under tmux and ours to use — hence the overlay window, which doesn't ask the terminal to draw anything at all.

**An agent's shell tool has no tty.** When Claude runs `show_profile.py` via its Bash tool, stdout is captured for the model rather than attached to the terminal, so *nothing* written there — escape sequence or plain text — reaches the user's screen. `profilegen/termstate.py::resolve_target_tty()` handles this: when stdout isn't a tty it asks tmux for the active pane's device (`#{pane_tty}`) and writes the sequences straight to it. That's safe only because badge/background move no cursor and paint no cells, so injecting them into a pane running a TUI is inert.

## Modes

| `--mode` | What it does | Where it works |
|---|---|---|
| `hud` | A small always-on-top, click-through overlay window pinned to a corner of the terminal window, showing the picture (animated for a GIF persona) and the name | macOS (needs `swiftc` from the Xcode command line tools) |
| `inline` | Inline image painted into the text grid via `termimg.py` | Plain terminals; degrades to a sliver under tmux |
| `state` | iTerm2 badge (name) + background image (picture) | iTerm2, incl. tmux — but **overwrites user-owned settings**, so it's opt-in only |
| `auto` (default) | `hud` where supported, else `inline` | — |
| `off` | Draws nothing | — |

`--clear` stops the overlay and clears any badge/background. `--avatar`, `--corner` (`tr`/`tl`/`br`/`bl`) and `--margin` tune the overlay's size and placement.

**Why `state` is never auto-selected.** It works by setting iTerm2's session background image — a slot that belongs to the user. Anyone with a configured background loses it, and clearing sets empty rather than restoring theirs. A feature shouldn't appropriate a user-owned setting, so `state` stayed available but demoted.

**Why the overlay is a separate window.** It consumes no terminal rows, touches no configuration, and doesn't depend on any terminal image protocol — so tmux, the shell and the emulator are all irrelevant to it, and animated GIF personas actually animate (via `NSImageView`, which drives GIF frames itself; drawing an `NSImage` by hand only ever renders frame one).

**tmux window awareness.** Several tmux windows share one terminal window, so "is the terminal frontmost" can't tell the overlay that its tmux window has been switched away from. The overlay is passed its `TMUX_PANE` and asks tmux (`#{window_active}#{session_attached}`) whether it should be on screen. For the same reason each pane gets its own pid file (`~/.cache/profile-gen/hud-<pane>.pid`) and stopping one persona's overlay never touches another session's.

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

Even with `allow-passthrough on`, plain tmux can only show an *inline* image for a moment, for the grid reason described at the top of this document. The default `hud` mode sidesteps this entirely and needs no tmux configuration at all — `allow-passthrough` only matters for `inline`/`state`. `tmux -CC attach` (iTerm2's native tmux integration, where iTerm2 renders each pane as a real window/tab instead of tmux painting a shared text grid) would make inline images work too, but it's a much bigger workflow change that the overlay makes unnecessary.

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

## Toggling display on/off after the fact

`scripts/toggle_display.py` flips a persona's stored `display.image`/`display.name` in place, without regenerating anything else about it:

```
python3 scripts/toggle_display.py --root <PROJECT_ROOT> [--slug SLUG] [--image on|off] [--name on|off]
```

It uses the same `<PROJECT_ROOT>/CLAUDE.md` discovery as `show_profile.py` (via the shared `profilegen.discovery` module), so it finds whichever persona(s) are currently referenced there — pass `--slug` to target just one if more than one is discovered. It edits whichever file that persona's content actually lives in: the standalone `persona.md`/`profiles/<slug>/<slug>.md` for `claude-md-ref`, or that persona's own marker-delimited region inside `CLAUDE.md` itself for a fully-embedded (`claude-md`) persona — `frontmatter.block_span()` confines the edit so a different embedded persona's block is never touched. Prints one JSON object per persona changed: `{"slug", "markdown_path", "display": {...}}`, or `{"error": "..."}` (nonzero exit) if no persona was found.

The `/display-profile` user command (`~/.claude/commands/display-profile.md`) wraps both scripts for interactive use: `/display-profile` previews, `/display-profile on|off` or `image on|off`/`name on|off` toggles then previews, and `/display-profile hook on|off` delegates the `SessionStart` hook setup above to the `update-config` skill.
