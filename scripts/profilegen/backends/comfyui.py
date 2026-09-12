"""ComfyUI backend: fully generic, driven by a user-supplied API-format workflow JSON.

Node-locating convention
-------------------------
Positive/negative prompt nodes are found by ``_meta.title`` (case-insensitive):
"ProfileGen Positive" / "positive" and "ProfileGen Negative" / "negative". When no
title matches, we fall back to a graph walk: find the first node whose class_type
is KSampler/KSamplerAdvanced/SamplerCustom, follow its "positive"/"negative" input
link back to the source CLIPTextEncode node.

The latent/size node is found by title "ProfileGen Latent", else by class_type
"EmptyLatentImage".

Seed is set on every node that has a "seed" or "noise_seed" input, to
``spec.seed`` (or a random 32-bit int if unset) -- the used value is reported in
``resolved["seed_used"]`` so it's consistent across all nodes touched.
"""
from __future__ import annotations

import json
import random
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .. import http
from .base import BackendError, ImageResult, NotSupported, PromptSpec

_SAMPLER_CLASSES = {"KSampler", "KSamplerAdvanced", "SamplerCustom"}
_POSITIVE_TITLES = {"profilegen positive", "positive"}
_NEGATIVE_TITLES = {"profilegen negative", "negative"}
_LATENT_TITLE = "profilegen latent"
_SEED_KEYS = ("seed", "noise_seed")


def _title(node: dict) -> str:
    return str(node.get("_meta", {}).get("title", "")).strip().lower()


def _find_by_title(workflow: dict, titles: set[str]) -> Optional[str]:
    for node_id, node in workflow.items():
        if _title(node) in titles:
            return node_id
    return None


def _find_sampler(workflow: dict) -> Optional[str]:
    for node_id, node in workflow.items():
        if node.get("class_type") in _SAMPLER_CLASSES:
            return node_id
    return None


def _resolve_link_source(workflow: dict, node_id: Optional[str], input_key: str) -> Optional[str]:
    if node_id is None:
        return None
    node = workflow.get(node_id)
    if not node:
        return None
    link = node.get("inputs", {}).get(input_key)
    if isinstance(link, list) and len(link) >= 1:
        return str(link[0])
    return None


def _find_latent_node(workflow: dict) -> Optional[str]:
    node_id = _find_by_title(workflow, {_LATENT_TITLE})
    if node_id is not None:
        return node_id
    for node_id, node in workflow.items():
        if node.get("class_type") == "EmptyLatentImage":
            return node_id
    return None


_OUTPUT_CLASSES = {"SaveImage", "VHS_VideoCombine"}


def _find_output_node(workflow: dict) -> Optional[str]:
    for node_id, node in workflow.items():
        if node.get("class_type") in _OUTPUT_CLASSES:
            return node_id
    return None


def _text_input_key(node: dict) -> str:
    inputs = node.get("inputs", {})
    if "text" in inputs:
        return "text"
    # fallback: first string-valued input
    for key, value in inputs.items():
        if isinstance(value, str):
            return key
    return "text"


def inject(workflow: dict, spec: PromptSpec) -> tuple[dict, dict]:
    """Mutate a copy of ``workflow`` with the given PromptSpec. Returns (workflow, resolved)
    where resolved is {positive_node, negative_node, seed_nodes, latent_node, seed_used}.
    """
    wf = json.loads(json.dumps(workflow))  # deep copy

    positive_node = _find_by_title(wf, _POSITIVE_TITLES)
    negative_node = _find_by_title(wf, _NEGATIVE_TITLES)

    if positive_node is None or negative_node is None:
        sampler_id = _find_sampler(wf)
        if positive_node is None:
            positive_node = _resolve_link_source(wf, sampler_id, "positive")
        if negative_node is None:
            negative_node = _resolve_link_source(wf, sampler_id, "negative")

    if positive_node is not None and positive_node in wf:
        node = wf[positive_node]
        key = _text_input_key(node)
        node.setdefault("inputs", {})[key] = spec.positive

    if negative_node is not None and negative_node in wf:
        node = wf[negative_node]
        key = _text_input_key(node)
        node.setdefault("inputs", {})[key] = spec.negative or ""

    latent_node = _find_latent_node(wf)
    if latent_node is not None and latent_node in wf:
        inputs = wf[latent_node].setdefault("inputs", {})
        inputs["width"] = spec.width
        inputs["height"] = spec.height

    seed_used = spec.seed if spec.seed is not None else random.getrandbits(32)
    seed_nodes: list[str] = []
    for node_id, node in wf.items():
        inputs = node.get("inputs", {})
        for seed_key in _SEED_KEYS:
            if seed_key in inputs:
                inputs[seed_key] = seed_used
                seed_nodes.append(node_id)

    resolved = {
        "positive_node": positive_node,
        "negative_node": negative_node,
        "seed_nodes": seed_nodes,
        "latent_node": latent_node,
        "output_node": _find_output_node(wf),
        "seed_used": seed_used,
    }
    return wf, resolved


def _load_workflow(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise BackendError(f"ComfyUI workflow file not found: {path}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise BackendError(f"Invalid JSON in ComfyUI workflow file {path}: {e}") from e


class ComfyUIBackend:
    name = "comfyui"

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.supports_native_gif = bool(cfg.get("comfyui_gif_workflow"))

    def validate(self, cfg: dict[str, Any]) -> list[str]:
        errors = []
        if not cfg.get("comfyui_url"):
            errors.append("comfyui_url is not set (env COMFYUI_URL)")
        workflow_path = cfg.get("comfyui_workflow")
        if not workflow_path:
            errors.append("comfyui_workflow is not set (env COMFYUI_WORKFLOW)")
        else:
            p = Path(workflow_path)
            if not p.exists():
                errors.append(f"comfyui_workflow file does not exist: {workflow_path}")
            else:
                try:
                    json.loads(p.read_text(encoding="utf-8"))
                except json.JSONDecodeError as e:
                    errors.append(f"comfyui_workflow is not valid JSON: {e}")
        return errors

    def _reachability_warning(self) -> Optional[str]:
        url = self.cfg.get("comfyui_url")
        if not url:
            return None
        try:
            http.get_json(f"{url.rstrip('/')}/system_stats", timeout=5)
            return None
        except Exception as e:
            return f"ComfyUI server not reachable at {url}: {e}"

    def _run_workflow(self, workflow_path: str, spec: PromptSpec, output_key: str) -> ImageResult:
        cfg = self.cfg
        url = cfg.get("comfyui_url")
        if not url:
            raise BackendError("comfyui_url is not set (env COMFYUI_URL)")
        if not workflow_path:
            raise BackendError("comfyui workflow is not set")
        url = url.rstrip("/")

        workflow = _load_workflow(workflow_path)
        injected, resolved = inject(workflow, spec)

        client_id = cfg.get("comfyui_client_id") or str(uuid.uuid4())
        resp = http.json_post(f"{url}/prompt", {}, {"prompt": injected, "client_id": client_id})
        prompt_id = resp.get("prompt_id")
        if not prompt_id:
            raise BackendError(f"ComfyUI did not return a prompt_id: {resp}")

        timeout_s = cfg.get("comfyui_timeout_s") or 600
        deadline = time.monotonic() + timeout_s
        history = None
        while time.monotonic() < deadline:
            hist_resp = http.get_json(f"{url}/history/{prompt_id}")
            if prompt_id in hist_resp:
                history = hist_resp[prompt_id]
                break
            time.sleep(1.5)
        if history is None:
            raise BackendError(
                f"Timed out after {timeout_s}s waiting for ComfyUI prompt {prompt_id} to complete"
            )

        outputs = history.get("outputs", {})
        entry = None
        for node_output in outputs.values():
            if output_key in node_output and node_output[output_key]:
                entry = node_output[output_key][0]
                break
        if entry is None:
            raise BackendError(
                f"ComfyUI history for prompt {prompt_id} contains no '{output_key}' outputs"
            )

        filename = entry.get("filename")
        subfolder = entry.get("subfolder", "")
        ftype = entry.get("type", "output")
        view_url = (
            f"{url}/view?filename={filename}&subfolder={subfolder}&type={ftype}"
        )
        data = http.get_bytes(view_url)

        fmt = "gif" if output_key == "gifs" else "png"
        return ImageResult(
            data=data,
            format=fmt,
            backend=self.name,
            model=Path(workflow_path).name,
            seed=resolved["seed_used"],
            width=spec.width,
            height=spec.height,
            raw_meta={"resolved": resolved, "prompt_id": prompt_id},
        )

    def generate_image(self, spec: PromptSpec) -> ImageResult:
        return self._run_workflow(self.cfg.get("comfyui_workflow"), spec, "images")

    def generate_gif(self, spec: PromptSpec) -> ImageResult:
        gif_workflow = self.cfg.get("comfyui_gif_workflow")
        if not gif_workflow:
            raise NotSupported("No comfyui_gif_workflow configured for this ComfyUI backend")
        return self._run_workflow(gif_workflow, spec, "gifs")
