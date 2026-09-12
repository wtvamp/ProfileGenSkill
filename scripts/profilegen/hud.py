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
HUD_DIR = Path(__file__).resolve().parent.parent / "hud"
SOURCE = HUD_DIR / "PersonaHUD.swift"
WINDOWS_SOURCE = HUD_DIR / "persona_hud.py"

# The orb's diameter for a roomy pane, and its floor. The overlay derives the actual size on every
# tick from the area it's pinned to (the tmux pane, or the whole terminal window outside tmux), so
# a narrow sidebar pane gets a proportionally smaller orb instead of one that covers half its
# text; these two just bound that.
DEFAULT_AVATAR = 104
DEFAULT_AVATAR_MIN = 40
DEFAULT_CORNER = "tr"
DEFAULT_MARGIN = 36


def _parent_pids_posix(pid: int) -> "list[tuple[int, str]]":
    chain = []
    for _ in range(12):
        if pid <= 1:
            break
        try:
            out = subprocess.run(
                ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            break
        parts = out.split(None, 1)
        if len(parts) != 2:
            break
        chain.append((pid, parts[1]))
        try:
            pid = int(parts[0])
        except ValueError:
            break
    return chain


def _parent_pids_windows(pid: int) -> "list[tuple[int, str]]":
    """Walk the process tree with CreateToolhelp32Snapshot, so no helper process is needed."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == -1:
        return []
    parents: dict[int, tuple[int, str]] = {}
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        ok = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            parents[entry.th32ProcessID] = (
                entry.th32ParentProcessID,
                entry.szExeFile.decode(errors="replace"),
            )
            ok = kernel32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)

    chain = []
    for _ in range(12):
        info = parents.get(pid)
        if info is None:
            break
        chain.append((pid, info[1]))
        pid = info[0]
        if pid <= 0:
            break
    return chain


def owner_pid() -> int | None:
    """PID of the Claude Code process this overlay belongs to.

    The overlay is deliberately detached so it outlives the command that launched it -- but that
    also means nothing would ever clean it up, and it would sit on screen long after the session
    it represents had exited. Handing the overlay this pid lets it exit on its own when the session
    does, with no hook or shutdown handshake to configure. Anything the shell tool runs is a
    descendant of Claude Code, so walking up the process tree finds it.
    """
    try:
        start = os.getppid()
    except OSError:
        return None
    try:
        walker = _parent_pids_windows if sys.platform.startswith("win") else _parent_pids_posix
        for pid, comm in walker(start):
            lowered = comm.lower()
            # "bg-spare" is a pre-warmed slot in the background-agent daemon pool, not a session --
            # it isn't tied to any one session's lifetime, so watching it would leave the overlay
            # orphaned (or worse, killed out from under a still-running session it never belonged
            # to). Skip past it and keep looking for the actual owning session further up.
            if "claude" in lowered and "bg-spare" not in lowered:
                return pid
    except Exception:
        return None
    return None


def _active_tmux_pane() -> str | None:
    """The tmux pane this call should be scoped to, found without trusting $TMUX_PANE.

    $TMUX_PANE is only set when this process itself was started *inside* the tmux pane it should
    act on. That's true for a plain foreground `claude` typed into a pane, but not for a session
    served through Claude Code's background-agent daemon (`--bg`, `/background`, a bg-spare
    worker) -- the daemon's worker pool has no tmux pane of its own to inherit one from, even
    when the *command that reached it* was typed into a real tmux pane. Trusting the env var in
    that case doesn't fail loudly, it just silently returns None every time, which is what made
    this look like "the overlay stopped respecting tmux" rather than "this session was never
    going to have $TMUX_PANE set in the first place".

    So: prefer the env var when it's actually there (the common case, and free). Otherwise ask
    the tmux server itself, which knows what's attached and active regardless of who's asking --
    the same fix and the same reasoning as watch-ci-in-tmux.sh's tmux-pane detection.
    """
    pane = os.environ.get("TMUX_PANE", "")
    if pane:
        return pane

    tmux_bin = shutil.which("tmux")
    if not tmux_bin:
        return None
    try:
        out = subprocess.run(
            [tmux_bin, "list-panes", "-a", "-F",
             "#{session_attached} #{window_active} #{pane_active} #{pane_id}"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None

    # All three, not just session_attached + pane_active: a tmux session commonly has more than
    # one window (a split made for something else, an old window left open), and each window
    # remembers its own "last active pane" even while a different window is the one actually on
    # screen -- so pane_active alone is ambiguous the moment there's a second window, and matches
    # whichever happens to come first in list-panes' output rather than the one truly visible.
    # window_active is what actually says "this is the window the client has up right now".
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == "1" and parts[1] == "1" and parts[2] == "1":
            return parts[3]
    return None


def _controlling_tty(pane: str | None) -> str | None:
    """The /dev/ttyNNN of the iTerm2 window hosting this session.

    Needed to target the right window when more than one iTerm2 window is open at once (see
    PersonaHUD.swift's windowFrame(forTTY:)) -- without it, the overlay just grabs whichever
    iTerm2 window happens to be frontmost/first in z-order, which is wrong the moment a second
    window exists: every persona's overlay ends up pinned to that one window instead of its own.

    Under tmux the pane's own pty is a *different* device from the iTerm2 window's pty (tmux
    allocates a fresh one per pane), so the pane's own controlling tty is useless here -- we ask
    tmux which client is attached to the pane's session and use that client's tty instead.
    Outside tmux, the owning process's own controlling tty already is the iTerm2 window's tty.
    """
    tmux_bin = shutil.which("tmux")
    if pane and tmux_bin:
        try:
            session = subprocess.run(
                [tmux_bin, "display-message", "-pt", pane, "-F", "#{session_name}"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
            if not session:
                return None
            out = subprocess.run(
                [tmux_bin, "list-clients", "-t", session, "-F", "#{client_tty}"],
                capture_output=True, text=True, timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
        tty = out.splitlines()[0].strip() if out else ""
        return tty or None

    pid = owner_pid()
    if pid is None:
        return None
    try:
        out = subprocess.run(
            ["ps", "-o", "tty=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out or out in ("??", "?"):
        return None
    return f"/dev/{out}"


def _pane_key() -> str:
    """Identifies the tmux pane this persona belongs to.

    Several Claude sessions, each with its own persona, commonly run in different tmux windows of
    the same terminal. Keying the pid file (and the kill) by pane is what keeps them independent:
    otherwise they'd share one pid file and stopping or relaunching one persona's overlay would
    kill the others'.
    """
    pane = _active_tmux_pane() or ""
    safe = "".join(ch for ch in pane if ch.isalnum())
    return safe or "default"


def _pid_file() -> Path:
    return CACHE_DIR / f"hud-{_pane_key()}.pid"


def _windows_interpreter() -> str | None:
    """`pythonw.exe` for preference, so launching the overlay doesn't flash a console window."""
    if not sys.platform.startswith("win"):
        return None
    candidate = Path(sys.executable).with_name("pythonw.exe")
    if candidate.is_file():
        return str(candidate)
    return shutil.which("pythonw") or sys.executable


def is_supported() -> bool:
    """macOS with a Swift compiler (Xcode command line tools), or Windows with tkinter."""
    if sys.platform == "darwin":
        return shutil.which("swiftc") is not None and SOURCE.is_file()
    if sys.platform.startswith("win"):
        if not WINDOWS_SOURCE.is_file():
            return False
        try:
            import tkinter  # noqa: F401
        except ImportError:
            return False
        return True
    return False


def ensure_built() -> Path | None:
    """The overlay executable for this platform, compiling it first where that's needed.

    On Windows the overlay is a Python script, so there's nothing to build; on macOS the Swift
    source is compiled into ``~/.cache/profile-gen`` on first use and recompiled whenever the
    source is newer, so no binary is checked in and the user never runs a build step.
    """
    if not is_supported():
        return None
    if sys.platform.startswith("win"):
        return WINDOWS_SOURCE
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
    avatar_min: int = DEFAULT_AVATAR_MIN,
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

    if sys.platform.startswith("win"):
        args = [_windows_interpreter() or sys.executable, str(binary)]
    else:
        args = [str(binary)]
    args += ["--avatar", str(avatar), "--avatar-min", str(avatar_min),
             "--corner", corner, "--margin", str(margin)]
    if image_path:
        args += ["--image", str(image_path)]
    if name:
        args += ["--name", str(name)]

    # Tell the overlay which tmux pane it belongs to, so it hides when that tmux window isn't the
    # one on screen -- tmux windows share a single terminal window, so the overlay can't work this
    # out from the terminal alone. See _active_tmux_pane()'s own comment for why this can't just
    # read $TMUX_PANE: a daemon-hosted session (--bg, /background) never has it set even when the
    # command that reached it came from a real tmux pane, and without it the overlay silently
    # falls back to targeting the *whole* terminal window -- still visible, but no longer clipped
    # to (or hidden by) the one pane it's actually supposed to belong to.
    pane = _active_tmux_pane()
    if pane:
        tmux_bin = shutil.which("tmux")
        if tmux_bin:
            args += ["--tmux-pane", pane, "--tmux-bin", tmux_bin]

    # Which physical iTerm2 window to draw over -- see _controlling_tty()'s docstring for why
    # this can't just be "whichever iTerm2 window is frontmost": with more than one iTerm2 window
    # open, that guess is wrong for every overlay except the one belonging to that window.
    if not sys.platform.startswith("win"):
        tty = _controlling_tty(pane)
        if tty:
            args += ["--tty", tty]

    # so the overlay exits by itself when the session it belongs to does
    watch = owner_pid()
    if watch:
        args += ["--watch-pid", str(watch)]

    # Detach so the overlay outlives the process that started it. Windows has no
    # start_new_session; DETACHED_PROCESS|CREATE_NO_WINDOW is the equivalent, and also keeps a
    # console window from flashing up.
    if sys.platform.startswith("win"):
        detach = {"creationflags": 0x00000008 | 0x08000000}
    else:
        detach = {"start_new_session": True}

    try:
        with open(os.devnull, "wb") as devnull:
            process = subprocess.Popen(args, stdout=devnull, stderr=devnull, **detach)
    except OSError:
        return False

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _pid_file().write_text(str(process.pid), encoding="utf-8")
    except OSError:
        pass
    return True
