import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen.backends.base import PromptSpec  # noqa: E402
from profilegen.backends.comfyui import inject  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_inject_titled_workflow_resolves_by_title():
    workflow = _load("workflow_txt2img.api.json")
    spec = PromptSpec(positive="a friendly robot", negative="blurry", seed=42, width=768, height=768)

    wf, resolved = inject(workflow, spec)

    assert resolved["positive_node"] == "2"
    assert resolved["negative_node"] == "3"
    assert resolved["latent_node"] == "4"
    assert resolved["output_node"] == "7"
    assert resolved["seed_used"] == 42

    assert wf["2"]["inputs"]["text"] == "a friendly robot"
    assert wf["3"]["inputs"]["text"] == "blurry"
    assert wf["4"]["inputs"]["width"] == 768
    assert wf["4"]["inputs"]["height"] == 768
    assert wf["5"]["inputs"]["seed"] == 42

    # original workflow dict must not be mutated
    assert workflow["2"]["inputs"]["text"] == "placeholder positive"


def test_inject_titled_workflow_seed_random_when_unset():
    workflow = _load("workflow_txt2img.api.json")
    spec = PromptSpec(positive="a friendly robot")

    _, resolved = inject(workflow, spec)

    assert isinstance(resolved["seed_used"], int)
    assert 0 <= resolved["seed_used"] < 2**32


def test_inject_untitled_workflow_falls_back_to_graph_walk():
    workflow = _load("workflow_untitled.api.json")
    spec = PromptSpec(positive="a mysterious wanderer", negative="low quality", seed=7)

    wf, resolved = inject(workflow, spec)

    assert resolved["positive_node"] == "2"
    assert resolved["negative_node"] == "3"
    assert resolved["latent_node"] == "4"
    assert resolved["output_node"] == "7"
    assert resolved["seed_used"] == 7

    assert wf["2"]["inputs"]["text"] == "a mysterious wanderer"
    assert wf["3"]["inputs"]["text"] == "low quality"
    assert wf["5"]["inputs"]["seed"] == 7


def test_inject_gif_workflow_uses_noise_seed_and_advanced_sampler():
    workflow = _load("workflow_gif.api.json")
    spec = PromptSpec(positive="a dancing fox", negative="static", seed=99)

    wf, resolved = inject(workflow, spec)

    assert resolved["positive_node"] == "2"
    assert resolved["negative_node"] == "3"
    assert resolved["output_node"] == "8"
    assert wf["6"]["inputs"]["noise_seed"] == 99


def test_inject_workflow_with_no_output_node_reports_none():
    workflow = _load("workflow_no_output.api.json")
    spec = PromptSpec(positive="no save node here")

    _, resolved = inject(workflow, spec)

    assert resolved["output_node"] is None
    # positive/negative/latent resolution still works even without a save node
    assert resolved["positive_node"] == "2"
    assert resolved["negative_node"] == "3"
    assert resolved["latent_node"] == "4"
