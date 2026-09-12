"""iTerm2 terminal-*state* persona display: badge (the name) and background image (the picture).

Why this exists alongside `termimg.py`'s inline-image protocols, and why it's the default:

**The tmux grid problem.** An inline image is painted into the terminal's text grid. tmux's own
screen model tracks only text cells -- it forwards the image bytes once (that's all
`allow-passthrough` buys you) and then has nothing to redraw, so the image is lost the moment
anything repaints the pane. In practice an inline image inside tmux shows a clipped sliver at
best. iTerm2's badge and background-image are *session state* instead: set once by an escape
sequence, rendered by iTerm2 outside the grid entirely, so tmux has nothing to clobber. Measured
on iTerm2 3.6.11 + tmux 3.7b -- inline fails under tmux, badge and background both work, and both
also work without tmux.

**The delivery problem.** An agent's shell tool usually runs with stdout captured for the model
rather than attached to the user's terminal, so *nothing* it writes -- escape sequence or plain
text -- reaches the screen. `resolve_target_tty()` asks tmux for the active pane's device so these
sequences can be written straight to it. That is only safe because badge/background move no cursor
and paint no cells: injecting them into a pane already running an interactive TUI is inert.

Both state sequences persist until changed, which is the point -- the persona stays visible rather
than scrolling away. Use `clear_badge()`/`clear_background_image()` to remove them.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys


def detect_iterm() -> bool:
    """iTerm2, including from inside tmux.

    ``$TERM_PROGRAM`` is rewritten to ``tmux`` inside a tmux session so it can't answer this on
    its own; ``$LC_TERMINAL`` is an ``LC_*`` variable iTerm2 sets that tmux (and ssh) forward,
    so it survives the nesting.
    """
    if os.environ.get("TERM_PROGRAM") == "iTerm.app":
        return True
    return os.environ.get("LC_TERMINAL", "").lower() == "iterm2"


def resolve_target_tty() -> str | None:
    """Device to write persona escape sequences to, or None meaning "just use stdout".

    Returns None when stdout is already a terminal (a SessionStart hook, or the user's own
    shell) -- writing there is correct and needs no indirection. When stdout is *not* a tty, it's
    being captured (an agent's shell tool), and nothing written to it can reach the user's screen
    at all; in that case ask tmux for the active pane's device and target that directly.
    """
    if sys.stdout.isatty():
        return None

    pane = os.environ.get("TMUX_PANE")
    if not pane or not os.environ.get("TMUX"):
        return None

    tmux_bin = shutil.which("tmux") or "/opt/homebrew/bin/tmux"
    try:
        result = subprocess.run(
            [tmux_bin, "display-message", "-pt", pane, "#{pane_tty}"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    return result.stdout.strip() or None


def _wrap_tmux(sequence: str) -> str:
    if not os.environ.get("TMUX"):
        return sequence
    return "\033Ptmux;" + sequence.replace("\033", "\033\033") + "\033\\"


def _b64(text: str) -> str:
    return base64.b64encode(str(text).encode("utf-8")).decode("ascii")


def _osc1337(payload: str) -> str:
    return f"\033]1337;{payload}\a"


def _emit(sequence: str, tty: str | None) -> bool:
    """Write one escape sequence to ``tty`` (or stdout when None). False on any failure --
    callers treat a persona failing to display as a no-op, never an error."""
    sequence = _wrap_tmux(sequence)
    try:
        if tty is None:
            sys.stdout.write(sequence)
            sys.stdout.flush()
        else:
            with open(tty, "w", encoding="utf-8") as handle:
                handle.write(sequence)
    except OSError:
        return False
    return True


def set_badge(text: str, tty: str | None = None) -> bool:
    """Show ``text`` as iTerm2's badge — large translucent text in the pane's corner."""
    return _emit(_osc1337("SetBadgeFormat=" + _b64(text)), tty)


def clear_badge(tty: str | None = None) -> bool:
    return set_badge("", tty)


def set_background_image(path: str, tty: str | None = None) -> bool:
    """Set the iTerm2 session's background image to ``path`` (a local file iTerm2 itself reads)."""
    return _emit(_osc1337("SetBackgroundImageFile=" + _b64(path)), tty)


def clear_background_image(tty: str | None = None) -> bool:
    return set_background_image("", tty)
