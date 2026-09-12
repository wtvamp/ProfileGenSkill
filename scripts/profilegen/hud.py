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

DEFAULT_AVATAR = 104
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
            if "claude" in comm.lower():
                return pid
    except Exception:
        return None
    return None


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
    args += ["--avatar", str(avatar), "--corner", corner, "--margin", str(margin)]
    if image_path:
        args += ["--image", str(image_path)]
    if name:
        args += ["--name", str(name)]

    # Tell the overlay which tmux pane it belongs to, so it hides when that tmux window isn't the
    # one on screen -- tmux windows share a single terminal window, so the overlay can't work this
    # out from the terminal alone.
    pane = os.environ.get("TMUX_PANE")
    if pane:
        tmux_bin = shutil.which("tmux")
        if tmux_bin:
            args += ["--tmux-pane", pane, "--tmux-bin", tmux_bin]

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
