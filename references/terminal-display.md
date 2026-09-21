# Terminal display reference

`scripts/show_profile.py` shows a persona's picture and/or name in the user's terminal. It never errors out over an unsupported terminal or a missing persona — a persona failing to display is not worth interrupting a session over, especially when it's meant to run unattended from a hook.

## The two problems, and why the overlay is the default

**tmux only tracks text cells.** An inline image is painted into the terminal's text grid. tmux forwards the image bytes once (that's all `allow-passthrough` buys you) and then has nothing in its model to redraw, so the image is lost on the next repaint — in practice a clipped sliver. Measured on iTerm2 3.6.11 + tmux 3.7b: inline images fail under tmux, while iTerm2's badge and background image work (they're session state rendered outside the grid). Sixel would be the one in-grid protocol tmux can natively track, but it isn't compiled into stock iTerm2 builds. The conclusion is that no *in-terminal* image channel is both reliable under tmux and ours to use — hence the overlay window, which doesn't ask the terminal to draw anything at all.

**An agent's shell tool has no tty.** When Claude runs `show_profile.py` via its Bash tool, stdout is captured for the model rather than attached to the terminal, so *nothing* written there — escape sequence or plain text — reaches the user's screen. `profilegen/termstate.py::resolve_target_tty()` handles this: when stdout isn't a tty it asks tmux for the active pane's device (`#{pane_tty}`) and writes the sequences straight to it. That's safe only because badge/background move no cursor and paint no cells, so injecting them into a pane running a TUI is inert.

## Modes

| `--mode` | What it does | Where it works |
|---|---|---|
| `hud` | A small always-on-top, click-through badge floating over the terminal window — the picture (animated for a GIF persona) and the name on a dark card, at the top centre of the pane | macOS (needs `swiftc` from the Xcode command line tools) and Windows (needs a Python with tkinter) |
| `inline` | Inline image painted into the text grid via `termimg.py` | Plain terminals; degrades to a sliver under tmux |
| `state` | iTerm2 badge (name) + background image (picture) | iTerm2, incl. tmux — but **overwrites user-owned settings**, so it's opt-in only |
| `auto` (default) | `hud` where supported, else `inline` | — |
| `off` | Draws nothing | — |

`--clear` stops the overlay and clears any badge/background. `--avatar`/`--avatar-min`, `--position` (`tc`/`c`/`bc` for horizontally centred at the top, middle or bottom, or `tr`/`tl`/`br`/`bl`) and `--margin` tune the overlay's size and placement. `--corner` still works as the old spelling of `--position`.

**The badge.** A rounded-square picture tile and the name, side by side on a small dark card, horizontally centred at the top of the pane. Four design choices, each answering something specific about drawing over a terminal:

- **A card behind everything.** Terminal output is high-contrast text in unpredictable colours, and white text floating directly on it is illegible about half the time. The card gives the name a consistent surface and makes the picture and the name read as one object rather than two floating fragments. On macOS it's a blurred backdrop (`NSVisualEffectView`) under a dark scrim — the blur stops it looking like a flat slab pasted on, and the scrim is what stops it *tinting*: vibrancy alone over a green diff hunk turns the whole card olive, and the one thing this surface has to be is the same colour every time. On Windows it's a flat dark fill, because `-transparentcolor` is a colour key rather than an alpha channel, so a pixel is either fully opaque or fully gone.
- **A rounded square, not a circle.** A square keeps the whole frame of the generated portrait where a circle crops its corners off, and it echoes the card's own rounded rectangle so the two shapes agree. The radius is 22% of the side, the ratio macOS uses for app icons — a sharp square reads as unstyled, this reads as intentional. A picture that isn't square is *centre-cropped* to fill the tile, never scaled to fit it: scaling a 16:9 portrait into a square visibly widens the face. On macOS that takes two views — the picture is laid out larger than the tile on its long axis and the tile clips the overflow, since a single view can only fit or stretch.
- **Concentric corners.** The card's radius is the tile's radius plus the padding between them, which keeps the two curves parallel. Deriving the card's radius from its own height instead is what turns a short badge into a pill.
- **A strip, not a stack.** The name sits to the right of the tile, vertically centred against it: a strip covers one or two lines of output where a stack covers several. The top edge is also where a pane's output is oldest and least likely to be the line being read.

Every measurement — padding, gap, corner radii, font size — is a fraction of the tile's side, so the badge looks identical at any size. Each axis of the placement is independently centred or inset from an edge; `--margin` is the inset for whichever axis isn't centred, and does nothing for one that is.

**The badge scales to its pane.** Under tmux the overlay is pinned over the persona's own pane, and the picture tile's side is 5% of that pane's width (or 15% of its height, whichever is smaller), clamped to `[--avatar-min, --avatar]` (26–48 pt by default); outside tmux the same rule applies to the whole terminal window. A half-width pane in a typical window lands at the 48 pt maximum, a third-width pane gets roughly 33 pt, and a sidebar drops to the floor. Width leads because text runs horizontally, so that's what a too-big badge covers; the height term only bites on short, wide bottom splits. Both fractions are the *tile's* side rather than the card's, since the card adds its padding outside them. The two platform implementations carry the same fractions, and `tests/test_hud.py` reads both source files to check they still agree — nothing at runtime couples a Swift file to a Python one, so a number tuned in one and not the other is otherwise a silent divergence.

**Why `state` is never auto-selected.** It works by setting iTerm2's session background image — a slot that belongs to the user. Anyone with a configured background loses it, and clearing sets empty rather than restoring theirs. A feature shouldn't appropriate a user-owned setting, so `state` stayed available but demoted.

**Why the overlay is a separate window.** It consumes no terminal rows, touches no configuration, and doesn't depend on any terminal image protocol — so tmux, the shell and the emulator are all irrelevant to it, and animated GIF personas actually animate (via `NSImageView`, which drives GIF frames itself; drawing an `NSImage` by hand only ever renders frame one).

**Two implementations, one interface.** `scripts/hud/PersonaHUD.swift` (macOS, AppKit `NSPanel`) and `scripts/hud/persona_hud.py` (Windows, tkinter + `ctypes`) take the same flags and behave the same way; `profilegen/hud.py` picks between them by platform. The macOS one is compiled on first use into `~/.cache/profile-gen` and recompiled when its source changes; the Windows one is a script, so there's nothing to build — it's launched with `pythonw.exe` where available and `DETACHED_PROCESS | CREATE_NO_WINDOW` so no console flashes up. On Windows, click-through comes from `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`, background transparency from tkinter's Windows-only `-transparentcolor`, and window tracking from `GetForegroundWindow`/`GetWindowRect` filtered by the foreground process name. Pillow, when installed, gives a circular avatar and smooth GIF frames; without it the fallback is a square avatar animated through `PhotoImage`'s frame index.

*Windows caveat, untested as of writing:* the overlay draws a Windows window, so it has to run on the Windows side. Under WSL it would need an explicit Windows interpreter rather than the WSL one, which `hud.py` doesn't attempt yet.

**Lifetime.** The overlay is detached so it survives the command that launched it, which means nothing else would ever clean it up — it would sit on screen long after the session it represents had exited. It's therefore given the pid of the Claude Code process that owns it (found by walking up the process tree, since anything the shell tool runs is a descendant of it) and exits by itself when that process goes away. No hook or shutdown handshake to configure. Note the existence check is `kill(pid, 0)` on POSIX but `OpenProcess`/`GetExitCodeProcess` on Windows — Python's `os.kill` calls `TerminateProcess` there for *any* signal, so the POSIX idiom would kill the very process it was meant to test.

**tmux pane awareness.** Several tmux windows share one terminal window, so "is the terminal frontmost" can't tell the overlay that its tmux window has been switched away from. A window can also be split into several panes each running its own agent, so pinning every overlay to the terminal window would stack them on top of each other. The overlay is passed its `TMUX_PANE` and asks tmux for `#{pane_left}`/`#{pane_top}`/`#{pane_right}`/`#{pane_bottom}` against `#{window_width}`/`#{window_height}`, then positions itself within *its own pane* — and hides entirely unless `#{window_active}` and `#{session_attached}` are both set. Each pane also gets its own pid file (`~/.cache/profile-gen/hud-<pane>.pid`) so stopping one persona's overlay never touches another session's.

## What gets shown, and when

Each persona's `display.image`/`display.name` fields (see `references/profile-schema.md`) control this — set at generation time via `--show-image`/`--no-image`/`--show-name`/`--no-name`, defaulting to `true`/`true`. A profile written before these fields existed is treated as `true` too.

`display.variant` answers a third question: not whether to draw a picture, but **which** picture. A persona has a SFW picture (`image`) and optionally an NSFW one (`image_nsfw`); `variant` is `sfw` or `nsfw` and decides which of them the overlay loads. It defaults to `sfw`, and `show_profile.py --variant sfw|nsfw` overrides it for one invocation without changing what's stored. Asking for a variant the persona has no picture for falls back to the one it does have rather than drawing nothing, and the JSON report says so via `variant_fell_back`. See `scripts/profilegen/variants.py`, which also explains how a profile written before variants existed is reinterpreted rather than broken.

`display.autostart` answers a different question: not *what* to draw, but whether this persona appears **on its own** at session start. It's consulted only under `--autostart-only`, which is what the `SessionStart` hook passes — so `autostart: false` keeps a persona fully displayable via `/display-profile` while stopping it appearing unprompted. Useful when several projects each have a persona and only some should announce themselves. Defaults to `true`, so personas written before the field keep appearing rather than silently stopping.

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

## A spoken self-introduction via the same hook

`scripts/session_intro.py` is a separate `SessionStart` hook script that makes Claude actually introduce itself at the top of a session — name, personality, and a one-sentence gesture at what's recently been touched. That signal is the most-recently-modified files under the project root (by mtime), read fresh on every session start — not the auto-memory index (`MEMORY.md`). An earlier version used the memory index and it produced a persona that confidently narrated a "most recently we've been working on..." story pulled from stale memory, unrelated to what was actually current; memory is written once and organized by topic, not chronology (see the memory system's own guidance on this), so it can describe work from weeks ago as if it were live. File mtimes can't be stale that way. `git log` is a fallback only, for a project where file recency isn't a useful signal. The prompt also explicitly tells Claude not to invent a narrative about *why* a file changed — just to notice *that* it did, and stay honest if it isn't sure. It's independent of the `hud`/`inline`/`state` display above (it prints text/context, not an image), so the two can be wired in together or separately.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 <SKILL_DIR>/scripts/session_intro.py --root \"$CLAUDE_PROJECT_DIR\""
          }
        ]
      }
    ]
  }
}
```

Same `<SKILL_DIR>` substitution as above. It emits two things, for two different reasons a `SessionStart` hook can't just make Claude talk before the user has said anything:

- `hookSpecificOutput.additionalContext` — primes Claude to open its *first reply* of the session with an in-character introduction. Only visible once the user actually sends a message.
- `systemMessage` — a short static one-liner (persona name + the latest commit subject) the harness displays immediately at session start, with no user input needed, so there's some visible greeting even before anyone types.

### Register it at one level only

Claude Code **merges** hook definitions from every settings file that applies to a session — a project's `.claude/settings.json`, an ancestor directory's, and `~/.claude/settings.json` — rather than letting the nearest one override the others. So a project nested inside another project that already registers this hook gets it twice, and the intro is emitted twice. Before adding the hook, check whether an ancestor directory (or the user-level `~/.claude/settings.json`) already has it, and if so leave the nested project alone — the ancestor's hook passes `$CLAUDE_PROJECT_DIR` and will resolve the right persona anyway.

`session_intro.py` also guards against this itself: the first invocation for a given `session_id` claims it via a lock file under `~/.cache/profile-gen/session-intro`, and any duplicate arriving within 30 seconds emits nothing. The claim expires rather than being permanent, so a later legitimate re-fire of the same session (`/clear` re-runs `SessionStart`) still introduces the persona. Any failure to take the claim — no `session_id` on stdin, an unwritable cache dir, no `flock` — falls through to emitting the intro, since a duplicated line is cosmetic while a missing one is the feature not working.

It discovers the persona the same way `show_profile.py --root` does (via `CLAUDE.md`'s profile-gen marker blocks), so no argument beyond `--root` is needed, and it degrades to emitting nothing (never an error) if there's no persona or the project isn't a git repo.

## Toggling display on/off after the fact

`scripts/toggle_display.py` flips a persona's stored display preferences in place, without regenerating anything else about it:

```
python3 scripts/toggle_display.py --root <PROJECT_ROOT> [--slug SLUG] [--image on|off] [--name on|off] [--autostart on|off] [--variant sfw|nsfw|toggle]
```

`--variant toggle` flips to whichever picture isn't currently showing; `--variant nsfw` on a persona with no NSFW picture is refused with an error rather than silently doing nothing, since the fix is to generate one with `/profile-gen`, not to try again here.

It uses the same `<PROJECT_ROOT>/CLAUDE.md` discovery as `show_profile.py` (via the shared `profilegen.discovery` module), so it finds whichever persona(s) are currently referenced there — pass `--slug` to target just one if more than one is discovered. It edits whichever file that persona's content actually lives in: the standalone `persona.md`/`profiles/<slug>/<slug>.md` for `claude-md-ref`, or that persona's own marker-delimited region inside `CLAUDE.md` itself for a fully-embedded (`claude-md`) persona — `frontmatter.block_span()` confines the edit so a different embedded persona's block is never touched. Prints one JSON object per persona changed: `{"slug", "markdown_path", "display": {...}}`, or `{"error": "..."}` (nonzero exit) if no persona was found.

The `/display-profile` user command (`~/.claude/commands/display-profile.md`) wraps both scripts for interactive use: `/display-profile` previews, `/display-profile on|off` or `image on|off`/`name on|off` toggles then previews, `/display-profile nsfw on|off|toggle` switches which picture is shown and re-draws, and `/display-profile hook on|off` delegates the `SessionStart` hook setup above to the `update-config` skill.
