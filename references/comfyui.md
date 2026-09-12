# ComfyUI workflow convention

**Don't have a workflow yet?** You don't need one — SKILL.md step 4a queries your server's
installed checkpoints/LoRAs (`scripts/inspect_comfyui.py`) and hands off to a subagent that
authors one for you, LoRA picks included, following the convention below (see
`references/comfyui-workflow-authoring.md`). Everything past this paragraph describes the
convention that both a hand-built and an auto-built workflow must follow.

The ComfyUI backend is fully generic: it takes any workflow exported in **API format**
(ComfyUI's "Save (API Format)" option, not the regular UI-format workflow save) and injects the
prompt text, seed, and size into it before submitting. Node resolution works two ways, tried in
order:

## 1. Title convention (preferred)

Give nodes in your workflow these titles (in the ComfyUI node's title field — right-click a node
→ Title, or set `_meta.title` directly in the exported JSON):

| Title | Node type | What gets set |
|---|---|---|
| `ProfileGen Positive` | `CLIPTextEncode` | `inputs.text` ← positive prompt |
| `ProfileGen Negative` | `CLIPTextEncode` | `inputs.text` ← negative prompt |
| `ProfileGen Latent` | `EmptyLatentImage` | `inputs.width`/`inputs.height` |

Matching is case-insensitive; `"positive"` and `"negative"` alone also match (so a node just
titled "Positive" works too).

## 2. Fallback: graph walk

If no matching titles are found, the backend finds the first node whose `class_type` is
`KSampler`, `KSamplerAdvanced`, or `SamplerCustom`, and follows that node's `positive`/`negative`
input links back to their source `CLIPTextEncode` nodes. This means an **unmodified workflow
exported straight from ComfyUI** (no manual titling) still works out of the box, as long as it has
a standard sampler wired to two text-encode nodes.

If no `EmptyLatentImage`-class node exists (titled or not), width/height are simply not injected —
the workflow's own defaults apply.

## Seed

Every node in the workflow that has a `seed` or `noise_seed` input gets set to the same value —
either the seed you passed in, or a random 32-bit int if none was given. The value actually used is
always reported back (in `check_config.py`'s dry-run output, and in the generated profile's
`generation.seed` field), so a run is reproducible after the fact.

## GIF workflows

Set `comfyui_gif_workflow` to a second API-format workflow (e.g. an AnimateDiff graph ending in a
`VHS_VideoCombine` node) to enable native animation. The same prompt/seed injection convention
applies. Output is located by walking the ComfyUI history's node outputs for a `"gifs"` list
(instead of `"images"` for the still-image workflow).

## Dry-run before spending compute

```bash
python3 scripts/check_config.py --backend comfyui --gif
```

reports exactly which node IDs were resolved (`positive_node`, `negative_node`, `latent_node`,
`seed_nodes`, `output_node`) without calling `/prompt` — use this to confirm your workflow will be
targeted correctly before running a real generation.
