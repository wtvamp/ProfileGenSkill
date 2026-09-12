"""Terminal inline-image display for profile-gen.

Supports the three inline-image mechanisms a user is realistically going to have available in a
Claude Code terminal session: iTerm2's own protocol (also implemented by WezTerm -- this is what
`imgcat` uses under the hood), the Kitty graphics protocol (also implemented by Ghostty and
others), and sixel via the external `img2sixel` binary as a last resort. Detection is env-var
based -- there is no safe way to probe a terminal's actual capability without risking corrupting
its state, so this errs toward "no image support" (silent no-op) over guessing wrong and dumping
raw escape codes into the user's prompt.

Sizing is expressed as a percentage of the terminal's width (``width_pct``, default 10 -- "10% of
the terminal window"). iTerm2 supports a native percentage width, so that one is exact. Kitty and
sixel have no percentage concept in their wire protocols, so both approximate it from
`shutil.get_terminal_size()` in character cells; a profile image is always square (see
`generate_image.py`'s center-crop), so the cell-to-pixel aspect ratio (roughly 1:2, most monospace
fonts) is used to keep it looking square rather than stretched. This is an approximation, not a
pixel-exact match to iTerm2's -- there is no portable way to query a terminal's exact cell pixel
size outside iTerm2/kitty-specific queries this module doesn't attempt.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path

_KITTY_CHUNK_SIZE = 4096


def detect_protocol() -> str | None:
    """Return "iterm", "kitty", "sixel", or None (no supported inline-image mechanism found)."""
    term_program = os.environ.get("TERM_PROGRAM", "")
    if term_program in ("iTerm.app", "WezTerm"):
        return "iterm"
    if os.environ.get("KITTY_WINDOW_ID") or os.environ.get("TERM") == "xterm-kitty":
        return "kitty"
    if shutil.which("img2sixel"):
        return "sixel"
    return None


def _wrap_tmux(sequence: str) -> str:
    """Wrap an escape sequence for tmux's passthrough mode.

    Requires `set -g allow-passthrough on` in the user's tmux config -- tmux blocks passthrough
    by default. Not detectable from here, so this always wraps when $TMUX is set and leaves it to
    the terminal to simply ignore the sequence if passthrough isn't enabled.
    """
    if not os.environ.get("TMUX"):
        return sequence
    escaped = sequence.replace("\033", "\033\033")
    return f"\033Ptmux;{escaped}\033\\"


def _target_cells(width_pct: int) -> tuple[int, int]:
    cols, _ = shutil.get_terminal_size(fallback=(80, 24))
    target_cols = max(1, round(cols * width_pct / 100))
    target_rows = max(1, target_cols // 2)
    return target_cols, target_rows


def _display_iterm2(png_bytes: bytes, width_pct: int) -> bool:
    """iTerm2's inline-image protocol (OSC 1337). Animates GIF bytes natively -- no special
    handling needed for an animated persona image."""
    encoded = base64.b64encode(png_bytes).decode("ascii")
    sequence = f"\033]1337;File=inline=1;width={width_pct}%;preserveAspectRatio=1:{encoded}\a"
    sys.stdout.write(_wrap_tmux(sequence))
    sys.stdout.flush()
    return True


def _kitty_helper() -> list[str] | None:
    """Prefer shelling out to kitty's own `icat` kitten when available -- it already handles GIF
    animation, tmux passthrough, and chunked transfer correctly; reimplementing all of that in
    the raw protocol below is not worth it for a feature this size."""
    kitten = shutil.which("kitten")
    if kitten:
        return [kitten, "icat"]
    icat = shutil.which("icat")
    if icat:
        return [icat]
    return None


def _display_kitty(png_path: Path, width_pct: int) -> bool:
    cols, rows = _target_cells(width_pct)
    helper = _kitty_helper()
    if helper:
        try:
            subprocess.run(
                [*helper, "--align", "left", "--place", f"{cols}x{rows}@0x0", str(png_path)],
                check=True,
            )
            return True
        except (OSError, subprocess.CalledProcessError):
            pass  # fall through to the raw protocol below

    # No `kitten`/`icat` on PATH: fall back to the raw graphics protocol, static images only --
    # it needs real PNG bytes (format 100), and a .gif isn't one, so skip rather than show a
    # broken/garbled first frame.
    if png_path.suffix.lower() == ".gif":
        return False

    png_bytes = png_path.read_bytes()
    encoded = base64.b64encode(png_bytes).decode("ascii")
    chunks = [encoded[i : i + _KITTY_CHUNK_SIZE] for i in range(0, len(encoded), _KITTY_CHUNK_SIZE)]
    if not chunks:
        return False

    parts = []
    for i, chunk in enumerate(chunks):
        more = 0 if i == len(chunks) - 1 else 1
        control = f"a=T,f=100,c={cols},r={rows},m={more}" if i == 0 else f"m={more}"
        parts.append(f"\033_G{control};{chunk}\033\\")
    sys.stdout.write(_wrap_tmux("".join(parts)))
    sys.stdout.flush()
    return True


def _display_sixel(png_path: Path, width_pct: int) -> bool:
    cols, _ = shutil.get_terminal_size(fallback=(80, 24))
    # img2sixel wants a pixel width; ~8px/cell approximates a common default monospace font --
    # good enough for a rough "10% of window" without querying exact terminal cell metrics.
    target_px = max(16, round(cols * 8 * width_pct / 100))
    try:
        result = subprocess.run(
            ["img2sixel", "-w", str(target_px), str(png_path)],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    sys.stdout.write(result.stdout.decode("ascii", errors="ignore"))
    sys.stdout.flush()
    return True


def display_image(png_path: str | Path, width_pct: int = 10, protocol: str | None = None) -> bool:
    """Show ``png_path`` inline in the current terminal, sized to roughly ``width_pct`` percent
    of its width. Returns True if something was actually displayed, False if no supported
    protocol was detected, the file doesn't exist, or the display attempt itself failed --
    callers should treat False as "silently skip", never as an error to surface.
    """
    path = Path(png_path)
    if not path.is_file():
        return False

    protocol = protocol or detect_protocol()
    if protocol is None:
        return False

    if protocol == "iterm":
        return _display_iterm2(path.read_bytes(), width_pct)
    if protocol == "kitty":
        return _display_kitty(path, width_pct)
    if protocol == "sixel":
        return _display_sixel(path, width_pct)
    return False
