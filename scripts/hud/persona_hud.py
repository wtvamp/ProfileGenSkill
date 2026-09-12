#!/usr/bin/env python3
"""PersonaHUD for Windows -- the tkinter/ctypes counterpart to PersonaHUD.swift.

Same idea and the same flags as the macOS overlay: a small always-on-top, click-through window
pinned to a corner of the terminal window, showing the persona's picture and name. It's a surface
we own outright, so it consumes no terminal rows, touches no user configuration, and needs no
terminal image protocol -- which is what makes it work regardless of terminal or multiplexer.

Uses only the standard library (tkinter + ctypes). Pillow is used when present for a circular
avatar and smooth GIF frames, and there's a plain-tkinter fallback (square avatar, GIF animated
via PhotoImage's frame index) so the overlay still works without it.

Known limitation: this draws a *Windows* window, so it must run on the Windows side. If Claude
Code is running under WSL, launching it from there would need an explicit Windows interpreter
(python.exe/pythonw.exe) rather than the WSL one -- profilegen/hud.py doesn't attempt that yet.
"""
from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
import tkinter as tk
from ctypes import wintypes

TRANSPARENT_KEY = "#010203"  # a colour the artwork is very unlikely to contain

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Fraction of the pinned area's shorter side the orb occupies -- the same constant as
# PersonaHUD.swift's avatarFraction, so the two platforms size identically for the same pane.
AVATAR_FRACTION = 0.3
# Orb sizes are snapped to this step so dragging a pane edge doesn't re-decode the GIF on every
# pixel of movement; frames are cached per snapped size.
AVATAR_STEP = 4

DEFAULT_OWNERS = (
    "windowsterminal.exe", "wt.exe", "conhost.exe", "openconsole.exe",
    "powershell.exe", "pwsh.exe", "cmd.exe", "alacritty.exe", "wezterm-gui.exe",
)

try:
    from PIL import Image, ImageDraw, ImageSequence, ImageTk
except ImportError:
    Image = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="")
    parser.add_argument("--name", default="")
    # `--avatar` is the orb's diameter for a roomy pane and `--avatar-min` its floor; the actual
    # size is derived every tick from the area the overlay is pinned to (see HUD._fit_to).
    parser.add_argument("--avatar", type=int, default=104)
    parser.add_argument("--avatar-min", type=int, default=40)
    parser.add_argument("--corner", default="tr", choices=["tr", "tl", "br", "bl"])
    parser.add_argument("--margin", type=int, default=36)
    parser.add_argument("--owner", default="", help="comma-separated terminal process names")
    parser.add_argument("--tmux-pane", default="")
    parser.add_argument("--tmux-bin", default="")
    parser.add_argument("--watch-pid", type=int, default=0)
    return parser.parse_args()


def _set_dpi_aware() -> None:
    """Without this, Windows scales the process and every coordinate we compute is wrong on a
    high-DPI display."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _process_name(hwnd: int) -> str:
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(260)
        buf = ctypes.create_unicode_buffer(size.value)
        if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size)
        ):
            return ""
        return buf.value.rsplit("\\", 1)[-1].lower()
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _foreground_terminal_rect(owners: tuple[str, ...]) -> tuple[int, int, int, int] | None:
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    if not hwnd or _process_name(hwnd) not in owners:
        return None
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def _pid_alive(pid: int) -> bool:
    """Whether the session that owns this overlay is still running.

    Deliberately not `os.kill(pid, 0)`: on Windows os.kill calls TerminateProcess for any signal,
    so the POSIX "signal 0 just tests existence" idiom would *kill* the process being checked.
    """
    if pid <= 0:
        return True
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259  # STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _tmux_pane_geometry(pane: str, tmux_bin: str):
    """Where this persona's pane sits as fractions of the terminal window, plus whether it's on
    screen: ``(fx0, fy0, fx1, fy1, visible)``, or None when not running under tmux.

    tmux multiplexes many *windows* into one terminal window (so the terminal being frontmost says
    nothing about whether this persona's window is displayed), and a window can hold several
    *panes* each running its own agent -- pinning every overlay to the terminal window's corner
    would stack them on top of each other. Positioning each overlay over its own pane keeps them
    apart and makes "which agent is in which pane" obvious.
    """
    if not pane or not tmux_bin:
        return None
    fmt = (
        "#{pane_left},#{pane_top},#{pane_right},#{pane_bottom},"
        "#{window_width},#{window_height},#{window_active},#{session_attached}"
    )
    try:
        out = subprocess.run(
            [tmux_bin, "display-message", "-pt", pane, fmt],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return (0.0, 0.0, 1.0, 1.0, False)

    try:
        left, top, right, bottom, cols, rows, active, attached = [int(v) for v in out.split(",")]
    except ValueError:
        return (0.0, 0.0, 1.0, 1.0, False)
    if cols <= 0 or rows <= 0:
        return (0.0, 0.0, 1.0, 1.0, False)

    # pane_right/pane_bottom are inclusive cell indices, hence the +1 for the far edges.
    return (
        left / cols,
        top / rows,
        (right + 1) / cols,
        (bottom + 1) / rows,
        active == 1 and attached == 1,
    )


class AvatarFrames:
    """Prepared avatar frames plus their durations, circular-masked where Pillow is available."""

    def __init__(self, path: str, size: int):
        self.frames: list[tk.PhotoImage] = []
        self.durations: list[int] = []
        if not path:
            return
        if Image is not None:
            self._load_with_pillow(path, size)
        else:
            self._load_with_tk(path)

    def _load_with_pillow(self, path: str, size: int) -> None:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        with Image.open(path) as src:
            for frame in ImageSequence.Iterator(src):
                rgba = frame.convert("RGBA")
                side = min(rgba.size)
                rgba = rgba.crop((
                    (rgba.width - side) // 2, (rgba.height - side) // 2,
                    (rgba.width + side) // 2, (rgba.height + side) // 2,
                )).resize((size, size), Image.LANCZOS)
                # composite onto the transparency key so the circle's corners drop out
                canvas = Image.new("RGB", (size, size), TRANSPARENT_KEY)
                canvas.paste(rgba, (0, 0), mask)
                self.frames.append(ImageTk.PhotoImage(canvas))
                self.durations.append(max(20, frame.info.get("duration", 100)))

    def _load_with_tk(self, path: str) -> None:
        # tkinter reads GIF frames by index and PNGs directly; no masking, so the avatar is square.
        index = 0
        while True:
            try:
                self.frames.append(tk.PhotoImage(file=path, format=f"gif -index {index}"))
            except tk.TclError:
                break
            self.durations.append(100)
            index += 1
        if not self.frames:
            try:
                self.frames.append(tk.PhotoImage(file=path))
                self.durations.append(100)
            except tk.TclError:
                pass


class HUD:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.owners = tuple(
            o.strip().lower() for o in args.owner.split(",") if o.strip()
        ) or DEFAULT_OWNERS

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT_KEY)
        self.root.attributes("-transparentcolor", TRANSPARENT_KEY)
        self.root.withdraw()

        # Frames are prepared per orb size and cached, so a pane that keeps flipping between two
        # sizes doesn't keep re-decoding the GIF. Starts at the maximum; the first tick fits it.
        self._frames_by_size: dict[int, AvatarFrames] = {}
        self.avatar_size = 0
        self.avatar = AvatarFrames("", 0)
        self.frame_index = 0
        self.image_label: tk.Label | None = None
        self.name_labels: list[tk.Label] = []

        if args.image:
            self.image_label = tk.Label(self.root, bd=0, bg=TRANSPARENT_KEY)
            self.image_label.pack()

        if args.name:
            # two offset labels fake a drop shadow, so the name stays legible over any background
            holder = tk.Frame(self.root, bg=TRANSPARENT_KEY)
            holder.pack(fill="x")
            shadow = tk.Label(holder, text=args.name, bd=0, bg=TRANSPARENT_KEY, fg="#000000")
            shadow.place(x=1, y=1, relwidth=1, anchor="nw")
            face = tk.Label(holder, text=args.name, bd=0, bg=TRANSPARENT_KEY, fg="#ffffff")
            face.pack(fill="x")
            self.name_labels = [shadow, face]

        self._fit_to(args.avatar)
        self._apply_click_through()

    def _fit_to(self, avatar: int) -> None:
        """Re-fit the orb and its label to a new diameter (no-op when unchanged)."""
        avatar = max(AVATAR_STEP, int(round(avatar / AVATAR_STEP)) * AVATAR_STEP)
        if avatar == self.avatar_size:
            return
        self.avatar_size = avatar
        if self.image_label is not None:
            if avatar not in self._frames_by_size:
                if len(self._frames_by_size) >= 12:
                    self._frames_by_size.clear()
                self._frames_by_size[avatar] = AvatarFrames(self.args.image, avatar)
            self.avatar = self._frames_by_size[avatar]
            self.frame_index = 0
            if self.avatar.frames:
                self.image_label.configure(image=self.avatar.frames[0])
        font = ("Segoe UI", max(8, round(avatar * 10 / 104)), "bold")
        for label in self.name_labels:
            label.configure(font=font)
        self.root.update_idletasks()

    def _avatar_size_for(self, width: float, height: float) -> int:
        """Orb diameter for a pinned area of this size -- a fraction of its shorter side, clamped
        to [--avatar-min, --avatar] so it neither vanishes nor outgrows the configured size."""
        wanted = min(width, height) * AVATAR_FRACTION
        return int(round(min(self.args.avatar, max(self.args.avatar_min, wanted))))

    def _apply_click_through(self) -> None:
        hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        styles = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        styles |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, styles)

    def _animate(self) -> None:
        if len(self.avatar.frames) > 1 and self.image_label is not None:
            self.frame_index = (self.frame_index + 1) % len(self.avatar.frames)
            self.image_label.configure(image=self.avatar.frames[self.frame_index])
            delay = self.avatar.durations[self.frame_index]
        else:
            delay = 500
        self.root.after(delay, self._animate)

    def _tick(self) -> None:
        if not _pid_alive(self.args.watch_pid):
            self.root.destroy()
            return
        rect = _foreground_terminal_rect(self.owners)
        if rect is None:
            self.root.withdraw()
            self.root.after(250, self._tick)
            return

        left, top, right, bottom = rect
        # Default target is the whole terminal window; under tmux, narrow it to this pane.
        pane = _tmux_pane_geometry(self.args.tmux_pane, self.args.tmux_bin)
        if pane is not None:
            fx0, fy0, fx1, fy1, visible = pane
            if not visible:
                self.root.withdraw()
                self.root.after(250, self._tick)
                return
            width, height = right - left, bottom - top
            left, right = left + fx0 * width, left + fx1 * width
            top, bottom = top + fy0 * height, top + fy1 * height

        # Size to the pane (or window) before placing, so the corner offset uses the new size.
        self._fit_to(self._avatar_size_for(right - left, bottom - top))

        w = self.root.winfo_width()
        h = self.root.winfo_height()
        m = self.args.margin
        x = left + m if self.args.corner.endswith("l") else right - w - m
        y = top + m if self.args.corner.startswith("t") else bottom - h - m
        self.root.geometry(f"+{int(x)}+{int(y)}")
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.after(250, self._tick)

    def run(self) -> None:
        self._animate()
        self._tick()
        self.root.mainloop()


def main() -> int:
    if not sys.platform.startswith("win"):
        print("persona_hud.py is the Windows overlay; use PersonaHUD.swift on macOS", file=sys.stderr)
        return 1
    _set_dpi_aware()
    HUD(parse_args()).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
