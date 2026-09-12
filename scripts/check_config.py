#!/usr/bin/env python3
"""CLI: validate backend config and, for ComfyUI, dry-run node resolution against the
configured workflow(s) without making any generation calls. Also verifies (when the server is
reachable) that every node class_type the workflow(s) reference is actually installed on the
live ComfyUI server -- this catches a workflow built around a node family (e.g. AnimateDiff,
LTX-Video, Wan2.x) that turned out not to actually be installed, before wasting a generation call on it
or silently falling back to a lesser GIF mode without saying why.

Prints one JSON object: {"ok", "backend", "resolved", "errors", "warnings"}.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import config  # noqa: E402
from profilegen.backends import get_backend  # noqa: E402
from profilegen.backends.base import PromptSpec  # noqa: E402

_SECRET_KEYS = {"openai_api_key", "xai_api_key"}


def _masked_cfg(cfg: dict) -> dict:
    return {k: ("<set>" if k in _SECRET_KEYS and v else ("<missing>" if k in _SECRET_KEYS else v)) for k, v in cfg.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate profile-gen backend config")
    parser.add_argument("--backend", required=True, choices=["chatgpt", "grok", "grok-cli", "comfyui", "mock"])
    parser.add_argument("--gif", action="store_true", help="also check gif capability")
    parser.add_argument("--workflow", help="override comfyui_workflow path (e.g. a freshly authored one)")
    parser.add_argument("--gif-workflow", help="override comfyui_gif_workflow path")
    args = parser.parse_args()

    cfg = config.resolve(
        args.backend,
        {"comfyui_workflow": args.workflow, "comfyui_gif_workflow": args.gif_workflow},
    )
    backend_cls = get_backend(args.backend)
    backend = backend_cls(cfg)

    errors = list(backend.validate(cfg))
    warnings: list[str] = []
    resolved = None

    if args.backend == "comfyui" and not errors:
        reachability_warning = backend._reachability_warning()
        if reachability_warning:
            warnings.append(reachability_warning)

        # Fetch the live server's installed node types so referenced-but-not-installed nodes
        # (e.g. a workflow built assuming AnimateDiff/LTX-Video/Wan2.x is present when it isn't) are
        # caught here, before any generation is attempted -- not discovered as a /prompt-time
        # failure, and not silently papered over by falling back to a lesser GIF mode.
        installed_class_types: set[str] | None = None
        if not reachability_warning:
            try:
                from profilegen.http import get_json

                object_info = get_json(f"{cfg.get('comfyui_url').rstrip('/')}/object_info")
                installed_class_types = set(object_info.keys())
            except Exception as e:
                warnings.append(f"Could not fetch /object_info to verify node availability: {e}")

        def _check_missing_nodes(workflow: dict, label: str) -> None:
            if installed_class_types is None:
                return
            used = {node.get("class_type") for node in workflow.values() if isinstance(node, dict)}
            missing = sorted(used - installed_class_types - {None})
            if missing:
                errors.append(
                    f"{label} workflow references node type(s) not installed on this ComfyUI "
                    f"server: {', '.join(missing)}"
                )

        try:
            from profilegen.backends.comfyui import inject

            workflow_path = cfg.get("comfyui_workflow")
            workflow = json.loads(Path(workflow_path).read_text(encoding="utf-8"))
            _check_missing_nodes(workflow, "image")
            _, image_resolved = inject(workflow, PromptSpec(positive="test prompt"))
            resolved = {"image": image_resolved}

            if args.gif:
                gif_workflow_path = cfg.get("comfyui_gif_workflow")
                if not gif_workflow_path:
                    warnings.append("--gif requested but comfyui_gif_workflow is not configured")
                else:
                    gif_workflow = json.loads(Path(gif_workflow_path).read_text(encoding="utf-8"))
                    _check_missing_nodes(gif_workflow, "gif")
                    _, gif_resolved = inject(gif_workflow, PromptSpec(positive="test prompt"))
                    resolved["gif"] = gif_resolved
        except Exception as e:
            errors.append(f"Could not dry-run node resolution: {e}")

    result = {
        "ok": len(errors) == 0,
        "backend": args.backend,
        "resolved": resolved,
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
