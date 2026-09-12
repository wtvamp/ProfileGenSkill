"""Build/launch/stop the PersonaHUD overlay window (macOS).

The HUD is a small always-on-top, click-through window pinned to a corner of the terminal window
-- see `scripts/hud/PersonaHUD.swift` for why an overlay rather than anything terminal-native:
inline images die under tmux, and iTerm2's background image is a *user-owned setting* that a
feature has no business appropriating. An overlay is a surface we own: no terminal rows consumed,
no user configuration touched, no dependence on terminal image protocols, and animated GIF
personas actually animate.

The Swift source is compiled on first use into ``~/.cache/profile-gen`` (swiftc ships with the
Xcode command line tools) and recompiled whenever the source is newer than the cached binary, so
there's no checked-in binary and no build step for the user to run.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "profile-gen"
BINARY = CACHE_DIR / "persona-hud"
SOURCE = Path(__file__).resolve().parent.parent / "hud" / "PersonaHUD.swift"

DEFAULT_AVATAR = 104
DEFAULT_CORNER = "tr"
DEFAULT_MARGIN = 36


def _pane_key() -> str:
    """Identifies the tmux pane this persona belongs to.

    Several Claude sessions, each with its own persona, commonly run in different tmux windows of
    the same terminal. Keying the pid file (and the kill) by pane is what keeps them independent:
    otherwise they'd share one pid file and stopping or relaunching one persona's overlay would
    kill the others'.
    """
    pane = os.environ.get("TMUX_PANE", "")
    safe = "".join(ch for ch in pane if ch.isalnum())
    return safe or "default"


def _pid_file() -> Path:
    return CACHE_DIR / f"hud-{_pane_key()}.pid"


def is_supported() -> bool:
    """macOS with a Swift compiler available (Xcode command line tools)."""
    return sys.platform == "darwin" and shutil.which("swiftc") is not None


def ensure_built() -> Path | None:
    """Compile the overlay if the cached binary is missing or older than its source."""
    if not is_supported() or not SOURCE.is_file():
        return None
    if BINARY.is_file() and BINARY.stat().st_mtime >= SOURCE.stat().st_mtime:
        return BINARY

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["swiftc", "-O", "-o", str(BINARY), str(SOURCE)],
            capture_output=True,
            check=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return BINARY if BINARY.is_file() else None


def stop() -> bool:
    """Stop this pane's overlay. True if one was actually stopped.

    Deliberately scoped to this pane -- never a blanket `pkill` of every overlay, which would take
    down the personas of other sessions running in other tmux windows.
    """
    pid_file = _pid_file()
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False

    stopped = False
    try:
        os.kill(pid, signal.SIGTERM)
        stopped = True
    except OSError:
        pass  # already gone
    pid_file.unlink(missing_ok=True)
    return stopped


def launch(
    image_path: str | None,
    name: str | None,
    avatar: int = DEFAULT_AVATAR,
    corner: str = DEFAULT_CORNER,
    margin: int = DEFAULT_MARGIN,
) -> bool:
    """Replace any running overlay with one showing ``image_path``/``name``. False if the overlay
    isn't available (non-macOS, no swiftc, or the build failed) -- callers fall back to another
    mode rather than treating that as an error."""
    if not image_path and not name:
        return False
    binary = ensure_built()
    if binary is None:
        return False

    stop()

    args = [str(binary), "--avatar", str(avatar), "--corner", corner, "--margin", str(margin)]
    if image_path:
        args += ["--image", str(image_path)]
    if name:
        args += ["--name", str(name)]

    # Tell the overlay which tmux pane it belongs to, so it hides when that tmux window isn't the
    # one on screen -- tmux windows share a single terminal window, so the overlay can't work this
    # out from the terminal alone.
    pane = os.environ.get("TMUX_PANE")
    tmux_bin = shutil.which("tmux")
    if pane and tmux_bin:
        args += ["--tmux-pane", pane, "--tmux-bin", tmux_bin]

    try:
        with open(os.devnull, "wb") as devnull:
            process = subprocess.Popen(
                args, stdout=devnull, stderr=devnull, start_new_session=True
            )
    except OSError:
        return False

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _pid_file().write_text(str(process.pid), encoding="utf-8")
    except OSError:
        pass
    return True
