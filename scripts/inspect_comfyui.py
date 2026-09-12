#!/usr/bin/env python3
"""CLI: query a ComfyUI server's /object_info and print a condensed inventory (checkpoints,
LoRAs, samplers, schedulers, animation-node availability) for a workflow author (a subagent,
per SKILL.md) to design a workflow against -- so users don't need a pre-built workflow JSON.

Prints one JSON object: {"ok", "url", "checkpoints", "loras", "samplers", "schedulers",
"has_animatediff", "animatediff_nodes", "has_video_combine", "errors"}.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from profilegen import config  # noqa: E402
from profilegen.comfyui_inventory import summarize  # noqa: E402
from profilegen.http import BackendError, get_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a ComfyUI server's installed models/nodes")
    parser.add_argument("--url", help="override comfyui_url")
    args = parser.parse_args()

    cfg = config.resolve("comfyui", {"comfyui_url": args.url})
    url = cfg.get("comfyui_url")

    if not url:
        print(json.dumps({"ok": False, "url": None, "errors": ["comfyui_url is not set (env COMFYUI_URL)"]}))
        return 1

    url = url.rstrip("/")
    try:
        object_info = get_json(f"{url}/object_info")
    except BackendError as e:
        print(json.dumps({"ok": False, "url": url, "errors": [str(e)]}))
        return 1

    inventory = summarize(object_info)
    result = {"ok": True, "url": url, "errors": [], **inventory}
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
