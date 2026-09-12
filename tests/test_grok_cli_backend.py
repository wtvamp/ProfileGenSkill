import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen.backends.base import BackendError, NotSupported, PromptSpec
from profilegen.backends.grok_cli import GrokCliBackend


def _fake_completed_process(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["grok"], returncode=returncode, stdout=stdout, stderr="")


def test_validate_reports_missing_binary():
    backend = GrokCliBackend({"grok_cli_bin": "definitely-not-a-real-binary-xyz"})
    errors = backend.validate({})
    assert any("not found on PATH" in e for e in errors)


def test_validate_ok_when_binary_present_and_version_succeeds(tmp_path):
    fake_bin = tmp_path / "grok"
    fake_bin.write_text("#!/bin/sh\necho ok\n")
    fake_bin.chmod(0o755)

    with patch("profilegen.backends.grok_cli.shutil.which", return_value=str(fake_bin)):
        backend = GrokCliBackend({"grok_cli_bin": str(fake_bin)})
        errors = backend.validate({})
    assert errors == []


def test_generate_image_happy_path(tmp_path, monkeypatch):
    home = tmp_path / "home"
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    session_id = "test-session-123"

    quoted_cwd = str(workdir.resolve()).replace("/", "%2F")
    session_dir = home / ".grok" / "sessions" / quoted_cwd / session_id
    session_dir.mkdir(parents=True)
    (session_dir / "images").mkdir()
    image_bytes = b"\x89PNG\r\n\x1a\nfake-png-bytes"
    (session_dir / "images" / "1.png").write_bytes(image_bytes)

    fake_result = {
        "text": "Here's your image: [images/1.png](images/1.png)",
        "sessionId": session_id,
        "total_cost_usd": 0.01,
    }

    with patch("profilegen.backends.grok_cli.shutil.which", return_value="/usr/bin/grok"), \
         patch("profilegen.backends.grok_cli.Path.home", return_value=home), \
         patch("profilegen.backends.grok_cli.subprocess.run") as mock_run:
        mock_run.return_value = _fake_completed_process(json.dumps(fake_result))

        backend = GrokCliBackend({"grok_cli_workdir": str(workdir)})
        result = backend.generate_image(PromptSpec(positive="a red circle"))

    assert result.data == image_bytes
    assert result.format == "png"
    assert result.backend == "grok-cli"
    assert result.raw_meta["session_id"] == session_id

    # confirm the CLI was invoked with /imagine and the expected flags
    called_args = mock_run.call_args.args[0]
    assert called_args[0] == "/usr/bin/grok"
    assert "-p" in called_args
    prompt_arg = called_args[called_args.index("-p") + 1]
    assert prompt_arg == "/imagine a red circle"
    assert "--output-format" in called_args and "json" in called_args
    assert "--yolo" in called_args


def test_generate_image_raises_backend_error_on_nonzero_exit(tmp_path):
    with patch("profilegen.backends.grok_cli.shutil.which", return_value="/usr/bin/grok"), \
         patch("profilegen.backends.grok_cli.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["grok"], returncode=1, stdout="", stderr="something went wrong"
        )

        backend = GrokCliBackend({"grok_cli_workdir": str(tmp_path / "workdir")})
        with pytest.raises(BackendError, match="something went wrong"):
            backend.generate_image(PromptSpec(positive="a red circle"))


def test_generate_image_raises_backend_error_when_media_path_missing(tmp_path):
    home = tmp_path / "home"
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    fake_result = {
        "text": "Here's your image: [images/1.png](images/1.png)",
        "sessionId": "missing-session",
    }

    with patch("profilegen.backends.grok_cli.shutil.which", return_value="/usr/bin/grok"), \
         patch("profilegen.backends.grok_cli.Path.home", return_value=home), \
         patch("profilegen.backends.grok_cli.subprocess.run") as mock_run:
        mock_run.return_value = _fake_completed_process(json.dumps(fake_result))

        backend = GrokCliBackend({"grok_cli_workdir": str(workdir)})
        with pytest.raises(BackendError, match="not found at the expected path"):
            backend.generate_image(PromptSpec(positive="a red circle"))


def test_generate_gif_not_supported_without_ffmpeg():
    with patch("profilegen.backends.grok_cli.shutil.which") as mock_which:
        mock_which.side_effect = lambda name: "/usr/bin/grok" if name == "grok" else None
        backend = GrokCliBackend({})
        assert backend.supports_native_gif is False
        with pytest.raises(NotSupported):
            backend.generate_gif(PromptSpec(positive="a cat"))
