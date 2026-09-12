"""Summarize a ComfyUI server's /object_info response into the small inventory a workflow
author (a subagent, per SKILL.md) actually needs: available checkpoints, LoRAs, samplers,
schedulers, and whether real native-animation node families (AnimateDiff-Evolved, LTX-Video,
Wan2.x, etc.) are installed.

Kept as pure parsing logic (no network) so it's unit-testable against a fixture dict; the
network fetch lives in scripts/inspect_comfyui.py.

Node-family detection is prefix/name-based on purpose, NOT a blind substring search. A previous
version matched any class_type containing "animatediff" anywhere, which produced false
positives against unrelated nodes that merely mention AnimateDiff in their name without being
it -- e.g. Impact-Pack's ``DetailerForEachPipeForAnimateDiff`` / ``MaskToSEGS_for_AnimateDiff``,
and some StableCascade nodes. That false positive told the workflow-authoring subagent
AnimateDiff was available when it wasn't, leading to workflows referencing a node
(``ADE_AnimateDiffLoaderWithContext`` or similar) that doesn't exist on the server -- which
either fails at generation time or gets silently abandoned in favor of the synthetic pan/zoom
GIF path, defeating the entire point of requesting a native animation. Real AnimateDiff-Evolved
loader nodes are reliably prefixed ``ADE_`` and contain "Loader"; that's what's checked here.
"""
from __future__ import annotations

from typing import Any

_CHECKPOINT_CLASSES = ("CheckpointLoaderSimple", "CheckpointLoader")
_LORA_CLASSES = ("LoraLoader", "LoraLoaderModelOnly")
_SAMPLER_CLASSES = ("KSampler", "KSamplerAdvanced")

# Real AnimateDiff-Evolved node classes are prefixed "ADE_"; a loader node specifically is what
# actually inserts motion into the model (other ADE_ nodes like keyframes/sampling-settings are
# supporting nodes that don't by themselves indicate a usable animation path). Prefix + "loader"
# substring, not a blind "animatediff" substring search anywhere in the name -- see module
# docstring for exactly why that was wrong.
def _is_animatediff_loader(class_type: str) -> bool:
    return class_type.startswith("ADE_") and "loader" in class_type.lower()


# LTX-Video is a genuinely different, non-AnimateDiff native video-generation family that may be
# installed instead (this skill doesn't assume any one family -- it reports what's really there
# and lets the workflow-authoring subagent choose). ComfyUI's LTX-Video nodes are prefixed
# "LTXV".
def _is_ltxv_node(class_type: str) -> bool:
    return class_type.upper().startswith("LTXV")


# Wan2.x (Alibaba's video-diffusion family) is a third independent native-animation path, exposed
# either via ComfyUI-core nodes (e.g. WanImageToVideo, WanAnimateToVideo, WanFirstLastFrameToVideo)
# or Kijai's ComfyUI-WanVideoWrapper node pack (e.g. WanVideoModelLoader, WanVideoSampler,
# WanVideoTextEncode). Both use an exact, case-sensitive "Wan" prefix (capital W, lowercase an) --
# this deliberately does NOT match "wanBlockSwap" (lowercase w) or names where "Wan"/"WAN" appears
# after the start (e.g. "ModelMergeWAN2_1", "LoadWanVideoClipTextEncoder", "SkipLayerGuidanceWanVideo")
# to avoid the same class of false positive the AnimateDiff detector was fixed for.
def _is_wan_node(class_type: str) -> bool:
    return class_type.startswith("Wan")


_VIDEO_COMBINE_MARKERS = ("vhs_videocombine",)


def _combo_options(node_info: dict, field: str, section: str = "required") -> list[str]:
    """Extract a combo (dropdown) input's option list, e.g. inputs.required.ckpt_name ->
    [[names...], {...}] -> names. Returns [] if the field isn't present or isn't a combo.
    """
    spec = node_info.get("input", {}).get(section, {}).get(field)
    if isinstance(spec, list) and spec and isinstance(spec[0], list):
        return [str(v) for v in spec[0]]
    return []


def summarize(object_info: dict[str, Any]) -> dict:
    """Return {checkpoints, loras, samplers, schedulers, has_animatediff, animatediff_nodes,
    has_ltxv, ltxv_nodes, has_wan, wan_nodes, has_native_animation, has_video_combine}.

    ``has_native_animation`` is the convenience flag callers should actually branch on: true iff
    at least one real animation-capable node family was detected AND a `VHS_VideoCombine`-style
    output node exists to actually produce a GIF/video from it. ``has_animatediff``/``has_ltxv``/
    ``has_wan`` tell you *which* family (or families -- a server can have more than one
    installed), so the workflow-authoring subagent can pick the right node structure -- see
    references/comfyui-workflow-authoring.md.
    """
    checkpoints: list[str] = []
    loras: list[str] = []
    samplers: list[str] = []
    schedulers: list[str] = []
    animatediff_nodes: list[str] = []
    ltxv_nodes: list[str] = []
    wan_nodes: list[str] = []
    has_video_combine = False

    for class_type, node_info in object_info.items():
        if not isinstance(node_info, dict):
            continue

        if class_type in _CHECKPOINT_CLASSES:
            checkpoints.extend(_combo_options(node_info, "ckpt_name"))

        if class_type in _LORA_CLASSES:
            loras.extend(_combo_options(node_info, "lora_name"))

        if class_type in _SAMPLER_CLASSES:
            samplers.extend(_combo_options(node_info, "sampler_name"))
            schedulers.extend(_combo_options(node_info, "scheduler"))

        if _is_animatediff_loader(class_type):
            animatediff_nodes.append(class_type)

        if _is_ltxv_node(class_type):
            ltxv_nodes.append(class_type)

        if _is_wan_node(class_type):
            wan_nodes.append(class_type)

        if class_type.lower() in _VIDEO_COMBINE_MARKERS:
            has_video_combine = True

    has_animatediff = bool(animatediff_nodes)
    has_ltxv = bool(ltxv_nodes)
    has_wan = bool(wan_nodes)

    return {
        "checkpoints": sorted(set(checkpoints)),
        "loras": sorted(set(loras)),
        "samplers": sorted(set(samplers)),
        "schedulers": sorted(set(schedulers)),
        "has_animatediff": has_animatediff,
        "animatediff_nodes": sorted(set(animatediff_nodes)),
        "has_ltxv": has_ltxv,
        "ltxv_nodes": sorted(set(ltxv_nodes)),
        "has_wan": has_wan,
        "wan_nodes": sorted(set(wan_nodes)),
        "has_video_combine": has_video_combine,
        "has_native_animation": (has_animatediff or has_ltxv or has_wan) and has_video_combine,
    }
