import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen.comfyui_inventory import summarize

_FIXTURE_OBJECT_INFO = {
    "CheckpointLoaderSimple": {
        "input": {"required": {"ckpt_name": [["realisticVision.safetensors", "dreamshaper.safetensors"]]}}
    },
    "LoraLoader": {
        "input": {
            "required": {
                "lora_name": [["anime_style_v2.safetensors", "detail_tweaker.safetensors"]],
                "strength_model": ["FLOAT", {"default": 1.0}],
            }
        }
    },
    "KSampler": {
        "input": {
            "required": {
                "sampler_name": [["euler", "dpmpp_2m"]],
                "scheduler": [["normal", "karras"]],
            }
        }
    },
    "ADE_AnimateDiffLoaderV1": {"input": {"required": {}}},
    "VHS_VideoCombine": {"input": {"required": {}}},
    "SaveImage": {"input": {"required": {"images": ["IMAGE", {}]}}},
}


def test_summarize_extracts_checkpoints_and_loras():
    result = summarize(_FIXTURE_OBJECT_INFO)
    assert result["checkpoints"] == ["dreamshaper.safetensors", "realisticVision.safetensors"]
    assert result["loras"] == ["anime_style_v2.safetensors", "detail_tweaker.safetensors"]


def test_summarize_extracts_samplers_and_schedulers():
    result = summarize(_FIXTURE_OBJECT_INFO)
    assert result["samplers"] == ["dpmpp_2m", "euler"]
    assert result["schedulers"] == ["karras", "normal"]


def test_summarize_detects_animatediff_and_video_combine():
    result = summarize(_FIXTURE_OBJECT_INFO)
    assert result["has_animatediff"] is True
    assert "ADE_AnimateDiffLoaderV1" in result["animatediff_nodes"]
    assert result["has_video_combine"] is True


def test_summarize_reports_no_animatediff_when_absent():
    minimal = {"CheckpointLoaderSimple": _FIXTURE_OBJECT_INFO["CheckpointLoaderSimple"]}
    result = summarize(minimal)
    assert result["has_animatediff"] is False
    assert result["animatediff_nodes"] == []
    assert result["has_video_combine"] is False


def test_summarize_handles_empty_object_info():
    result = summarize({})
    assert result["checkpoints"] == []
    assert result["loras"] == []
    assert result["has_animatediff"] is False


def test_summarize_does_not_false_positive_on_impact_pack_and_cascade_nodes():
    """Regression test: a real server was observed reporting has_animatediff: true purely
    because these unrelated node names contain the substring "animatediff" -- AnimateDiff-Evolved
    (the ADE_ node family) was not actually installed. The detector must not match these.
    """
    fixture = {
        "DetailerForEachPipeForAnimateDiff": {"input": {"required": {}}},
        "MaskToSEGS_for_AnimateDiff": {"input": {"required": {}}},
    }
    result = summarize(fixture)
    assert result["has_animatediff"] is False
    assert result["animatediff_nodes"] == []
    assert result["has_native_animation"] is False


def test_summarize_detects_ltxv_nodes():
    fixture = {
        "LTXVLoader": {"input": {"required": {}}},
        "VHS_VideoCombine": {"input": {"required": {}}},
    }
    result = summarize(fixture)
    assert result["has_ltxv"] is True
    assert "LTXVLoader" in result["ltxv_nodes"]
    assert result["has_native_animation"] is True


def test_has_native_animation_requires_video_combine_output():
    # a real animation-capable node family with no way to actually produce a GIF/video isn't
    # usable end to end.
    fixture = {"ADE_AnimateDiffLoaderV1": {"input": {"required": {}}}}
    result = summarize(fixture)
    assert result["has_animatediff"] is True
    assert result["has_video_combine"] is False
    assert result["has_native_animation"] is False


def test_has_native_animation_true_with_animatediff_and_video_combine():
    result = summarize(_FIXTURE_OBJECT_INFO)
    assert result["has_native_animation"] is True


def test_summarize_detects_wan_nodes_core_and_wrapper():
    fixture = {
        "WanImageToVideo": {"input": {"required": {}}},
        "WanAnimateToVideo": {"input": {"required": {}}},
        "WanVideoModelLoader": {"input": {"required": {}}},
        "VHS_VideoCombine": {"input": {"required": {}}},
    }
    result = summarize(fixture)
    assert result["has_wan"] is True
    assert set(result["wan_nodes"]) == {"WanImageToVideo", "WanAnimateToVideo", "WanVideoModelLoader"}
    assert result["has_native_animation"] is True


def test_summarize_does_not_false_positive_on_wan_adjacent_node_names():
    """Regression test against real names observed on a live server: these all reference "Wan"
    somewhere but are not themselves Wan generation nodes with the exact "Wan" prefix (a
    lowercase-w utility node, a model-merge utility, and loader/patch nodes where "Wan" is not
    the leading token) -- the detector must not count these as evidence Wan is usable.
    """
    fixture = {
        "wanBlockSwap": {"input": {"required": {}}},
        "ModelMergeWAN2_1": {"input": {"required": {}}},
        "LoadWanVideoClipTextEncoder": {"input": {"required": {}}},
        "SkipLayerGuidanceWanVideo": {"input": {"required": {}}},
        "TorchCompileModelWanVideo": {"input": {"required": {}}},
        "DummyComfyWanModelObject": {"input": {"required": {}}},
    }
    result = summarize(fixture)
    assert result["has_wan"] is False
    assert result["wan_nodes"] == []


def test_summarize_detects_wan_versioned_node_names():
    # Wan2.1/2.2-specific nodes are still prefixed exactly "Wan" even with a version digit
    # immediately after (e.g. "Wan22FunControlToVideo", "Wan21BlockLoraSelect").
    fixture = {
        "Wan22FunControlToVideo": {"input": {"required": {}}},
        "Wan21BlockLoraSelect": {"input": {"required": {}}},
    }
    result = summarize(fixture)
    assert result["has_wan"] is True
    assert set(result["wan_nodes"]) == {"Wan22FunControlToVideo", "Wan21BlockLoraSelect"}


def test_has_native_animation_true_with_multiple_families_present():
    fixture = {
        **_FIXTURE_OBJECT_INFO,
        "LTXVLoader": {"input": {"required": {}}},
        "WanImageToVideo": {"input": {"required": {}}},
    }
    result = summarize(fixture)
    assert result["has_animatediff"] is True
    assert result["has_ltxv"] is True
    assert result["has_wan"] is True
    assert result["has_native_animation"] is True
