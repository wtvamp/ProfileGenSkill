import json
import os
import subprocess
import sys
from pathlib import Path

from mock_comfyui_server import start_server

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _run_check_config(comfyui_url, workflow, gif_workflow=None, gif=False):
    env = {**os.environ, "COMFYUI_URL": comfyui_url, "COMFYUI_WORKFLOW": str(workflow)}
    args = [sys.executable, "scripts/check_config.py", "--backend", "comfyui"]
    if gif_workflow:
        env["COMFYUI_GIF_WORKFLOW"] = str(gif_workflow)
    if gif:
        args.append("--gif")
    return subprocess.run(args, capture_output=True, text=True, cwd=str(REPO_ROOT), env=env)


def test_check_config_passes_when_all_nodes_installed():
    server, thread = start_server(port=0)
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        result = _run_check_config(url, FIXTURES / "workflow_txt2img.api.json")
        report = json.loads(result.stdout)
        assert report["ok"] is True, report
        assert report["errors"] == []
    finally:
        server.shutdown()


def test_check_config_reports_missing_node_for_phantom_animatediff():
    """Regression test for the real bug: a workflow built around a node family the server
    doesn't actually have installed (e.g. AnimateDiff-Evolved) must be caught here -- as a hard
    error naming the missing node type -- rather than only failing later at generation time or
    silently falling back to a lesser GIF mode.
    """
    server, thread = start_server(port=0)
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        result = _run_check_config(
            url,
            FIXTURES / "workflow_txt2img.api.json",
            gif_workflow=FIXTURES / "workflow_gif.api.json",
            gif=True,
        )
        report = json.loads(result.stdout)
        assert report["ok"] is False
        assert any("ADE_AnimateDiffLoaderGen1" in e for e in report["errors"]), report["errors"]
        assert any("not installed" in e for e in report["errors"]), report["errors"]
    finally:
        server.shutdown()
