"""Grok CLI backend: generates images/GIFs via the locally-installed `grok` CLI's `/imagine`
and `/imagine-video` slash commands, authenticated with `grok login` (the user's Grok/X
subscription) instead of a separate xAI API key.

This is fundamentally different from the other backends: it shells out to an *agentic* CLI
tool (one full agent turn per call) rather than calling a parameterized HTTP API. Consequences,
documented in references/backends.md:

- No seed control, and width/height are ignored (the CLI only takes a text description).
- Each call costs real usage on the user's account (reported back in raw_meta["cost_usd"]).
- The NSFW flag is still passed through in the prompt text, but the underlying Grok agent may
  apply its own judgment/guardrails around the request -- unlike a raw API call, this skill
  cannot force-override that from outside.
- The generated file's location is discovered by parsing the CLI's own JSON response (an
  ``images/<n>.<ext>`` style relative link in its "text" field) and resolving it against the
  session directory the CLI itself uses (``~/.grok/sessions/<url-quoted-cwd>/<session_id>/...``).
  This is the CLI's actual on-disk layout as observed, not a documented public contract -- if a
  future grok CLI version changes it, calls will fail with a clear BackendError rather than
  silently returning a wrong file.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from .base import BackendError, ImageResult, NotSupported, PromptSpec

_MEDIA_LINK_RE = re.compile(r"\(([^()\s]+\.(?:png|jpe?g|webp|gif|mp4))\)", re.IGNORECASE)

_DEFAULT_TIMEOUT_S = 300


class GrokCliBackend:
    name = "grok-cli"

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self._bin = cfg.get("grok_cli_bin") or "grok"
        self._bin_path = shutil.which(self._bin)
        self._ffmpeg_path = shutil.which("ffmpeg")
        self.supports_native_gif = bool(self._bin_path) and bool(self._ffmpeg_path)

    def validate(self, cfg: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if not self._bin_path:
            errors.append(
                f"grok CLI not found on PATH (expected binary: {self._bin!r}). "
                "Install it, or set grok_cli_bin/GROK_CLI_BIN to its full path."
            )
            return errors
        try:
            subprocess.run(
                [self._bin_path, "--version"],
                capture_output=True,
                timeout=15,
                check=True,
            )
        except Exception as e:
            errors.append(f"grok CLI found at {self._bin_path} but `--version` failed: {e}")
        return errors

    def _workdir(self) -> Path:
        workdir = Path(
            self.cfg.get("grok_cli_workdir")
            or (Path.home() / ".claude" / "profile-gen" / "grok-cli-runs")
        )
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir.resolve()

    def _run(self, prompt: str) -> dict:
        if not self._bin_path:
            raise BackendError(
                f"grok CLI not found on PATH (expected binary: {self._bin!r})"
            )
        workdir = self._workdir()
        timeout_s = self.cfg.get("grok_cli_timeout_s") or _DEFAULT_TIMEOUT_S

        try:
            proc = subprocess.run(
                [self._bin_path, "-p", prompt, "--output-format", "json", "--yolo"],
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as e:
            raise BackendError(f"grok CLI timed out after {timeout_s}s: {e}") from e

        if proc.returncode != 0:
            raise BackendError(
                f"grok CLI exited {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}"
            )

        try:
            result = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            raise BackendError(
                f"Could not parse grok CLI JSON output: {e}. Raw stdout: {proc.stdout[:500]!r}"
            ) from e

        return result

    def _resolve_media_path(self, result: dict, workdir: Path) -> Path:
        text = result.get("text", "")
        session_id = result.get("sessionId")
        match = _MEDIA_LINK_RE.search(text)
        if not match or not session_id:
            raise BackendError(
                "Could not find a generated media path in grok CLI output. "
                f"session_id={session_id!r} raw_text={text[:500]!r}"
            )
        relative_path = match.group(1)
        quoted_cwd = quote(str(workdir), safe="")
        media_path = (
            Path.home() / ".grok" / "sessions" / quoted_cwd / session_id / relative_path
        )
        if not media_path.exists():
            raise BackendError(
                f"grok CLI reported media at {relative_path!r} but it was not found at the "
                f"expected path {media_path} (session {session_id})"
            )
        return media_path

    def generate_image(self, spec: PromptSpec) -> ImageResult:
        workdir = self._workdir()
        result = self._run(f"/imagine {spec.positive}")
        media_path = self._resolve_media_path(result, workdir)

        fmt = media_path.suffix.lstrip(".").lower()
        if fmt == "jpg":
            fmt = "jpeg"

        return ImageResult(
            data=media_path.read_bytes(),
            format=fmt,
            backend=self.name,
            model="grok-cli",
            seed=None,
            width=None,
            height=None,
            raw_meta={
                "session_id": result.get("sessionId"),
                "cost_usd": result.get("total_cost_usd"),
                "raw_text": result.get("text"),
            },
        )

    def generate_gif(self, spec: PromptSpec) -> ImageResult:
        if not self.supports_native_gif:
            raise NotSupported(
                "grok-cli native GIF requires both the grok CLI and ffmpeg on PATH "
                "(ffmpeg converts /imagine-video's output video to a GIF)"
            )

        workdir = self._workdir()
        result = self._run(f"/imagine-video {spec.positive}")
        media_path = self._resolve_media_path(result, workdir)

        gif_path = media_path.with_suffix(".gif")
        try:
            subprocess.run(
                [
                    self._ffmpeg_path,
                    "-y",
                    "-i",
                    str(media_path),
                    "-vf",
                    "fps=10,scale=512:-1:flags=lanczos",
                    "-loop",
                    "0",
                    str(gif_path),
                ],
                capture_output=True,
                timeout=120,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise BackendError(
                f"ffmpeg failed to convert {media_path} to GIF: {e.stderr.decode('utf-8', errors='replace')}"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise BackendError(f"ffmpeg timed out converting {media_path} to GIF: {e}") from e

        return ImageResult(
            data=gif_path.read_bytes(),
            format="gif",
            backend=self.name,
            model="grok-cli",
            seed=None,
            width=None,
            height=None,
            raw_meta={
                "session_id": result.get("sessionId"),
                "cost_usd": result.get("total_cost_usd"),
                "raw_text": result.get("text"),
                "source_video": str(media_path),
            },
        )
