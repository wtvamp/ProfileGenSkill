# Authoring a ComfyUI workflow (for the workflow-building subagent)

You've been handed a ComfyUI server inventory (from `scripts/inspect_comfyui.py`) and a persona
description. Your job: write an **API-format** ComfyUI workflow JSON file that this skill's
`inject()` function (`scripts/profilegen/backends/comfyui.py`) can drive, and pick sensible
LoRAs from what's actually installed. Do not invent checkpoint or LoRA filenames that aren't in
the inventory — if the inventory has no checkpoints at all, say so instead of writing a workflow
that will fail to load.

## Required node-title convention

`inject()` looks for nodes by `_meta.title` (case-insensitive) first, falling back to a
graph-walk. Use the explicit titles — it's more reliable and it's what this skill's tests exercise:

- The node whose text becomes the subject/style prompt: `_meta.title: "ProfileGen Positive"`
  (a `CLIPTextEncode` node).
- The negative-prompt node: `_meta.title: "ProfileGen Negative"` (a `CLIPTextEncode` node).
- The size node: `_meta.title: "ProfileGen Latent"` (an `EmptyLatentImage` node) — `inject()`
  overwrites its `width`/`height` inputs.
- Every node with a `seed` or `noise_seed` input gets it overwritten by `inject()` automatically
  — no title needed for that.
- Exactly one output node: a `SaveImage` node (for a still-image workflow) or a
  `VHS_VideoCombine` node with `format: "image/gif"` (for a GIF workflow).

## Minimal still-image workflow shape

```json
{
  "1": {"class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "<a checkpoint from the inventory>"}},
  "2": {"class_type": "CLIPTextEncode", "_meta": {"title": "ProfileGen Positive"},
        "inputs": {"text": "", "clip": ["1", 1]}},
  "3": {"class_type": "CLIPTextEncode", "_meta": {"title": "ProfileGen Negative"},
        "inputs": {"text": "", "clip": ["1", 1]}},
  "4": {"class_type": "EmptyLatentImage", "_meta": {"title": "ProfileGen Latent"},
        "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
  "5": {"class_type": "KSampler",
        "inputs": {"seed": 0, "steps": 24, "cfg": 6.5, "sampler_name": "<from inventory>",
                    "scheduler": "<from inventory>", "denoise": 1.0,
                    "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0],
                    "latent_image": ["4", 0]}},
  "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
  "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "profile-gen"}}
}
```

Leave `text` fields on nodes 2/3 as empty strings — `inject()` fills them in at generation time.
`seed` on node 5 is likewise overwritten by `inject()`; put any placeholder integer there.

## Adding LoRAs

For each LoRA you choose (0-2 is typical; don't stack more than that without a reason), insert a
`LoraLoader` node between the checkpoint and the sampler/text-encode nodes, chaining `model`/
`clip` through it:

```json
"1b": {"class_type": "LoraLoader",
       "inputs": {"lora_name": "<a lora from the inventory>", "strength_model": 0.8,
                  "strength_clip": 0.8, "model": ["1", 0], "clip": ["1", 1]}}
```

Then point nodes 2/3/5's `model`/`clip` inputs at `["1b", 0]`/`["1b", 1]` instead of `["1", ...]`
(chain multiple LoRAs by feeding one's outputs into the next's inputs). Only reference LoRA
filenames that appear in the inventory's `loras` list — match on what the filename suggests
about style (realism, anime, specific art styles, etc.) against the persona's description.

**Never select a LoRA (or checkpoint) that names or clearly represents a specific real,
identifiable person** — a real name in the filename/path (e.g. a `celeb/` folder, a named public
figure, an actor), regardless of how well it might otherwise match the persona's described
appearance. This is a hard rule, not a style preference: generating a likeness of a real person
is out of bounds for this skill no matter which backend can technically do it. If the only LoRAs
that match the requested look are real-person ones, pick a generic/style LoRA instead (or none)
and say so in your report — don't substitute a real-person LoRA because nothing else fit as well.

Report which LoRAs you picked and why in your response, so the orchestrating skill can tell the
user.

## GIF workflow (only when the inventory reports `has_native_animation: true`)

**Trust the inventory's actual node lists, not vibes.** `has_animatediff`/`has_ltxv`/`has_wan`
are each computed from a strict, name-prefix match against the server's real `/object_info` —
not a loose "sounds like AnimateDiff" guess — specifically because a looser match previously
produced false positives (nodes like `DetailerForEachPipeForAnimateDiff` that merely mention
AnimateDiff in their name without being it), which led to workflows referencing nodes that don't
actually exist on the server. Don't second-guess this by assuming a family is available because
you'd expect a "real" ComfyUI setup to have it — if `has_animatediff`, `has_ltxv`, and `has_wan`
are all false, there is no native animation path on this server; tell the orchestrator so it
falls back to the synthetic GIF path (see `references/prompting.md`), and stop here.

If any are true, build a second workflow file using the same checkpoint/LoRA/prompt nodes as the
still-image workflow, per whichever family is actually present:

- **AnimateDiff** (`has_animatediff: true`, real loader class_type(s) in `animatediff_nodes`):
  insert that AnimateDiff loader node between the checkpoint and sampler.
- **LTX-Video** (`has_ltxv: true`, node class_types in `ltxv_nodes`): use those nodes to build an
  LTX-based generation graph instead — LTX is a different video-diffusion family with its own
  node set (not an AnimateDiff drop-in), so base the graph on what `ltxv_nodes` actually lists
  rather than assuming AnimateDiff's node shape applies.
- **Wan2.x** (`has_wan: true`, node class_types in `wan_nodes`): also a distinct family, exposed
  either via ComfyUI-core nodes (`WanImageToVideo`, `WanFirstLastFrameToVideo`, etc.) or Kijai's
  ComfyUI-WanVideoWrapper node pack (`WanVideoModelLoader`, `WanVideoSampler`,
  `WanVideoTextEncode`, `WanVideoDecode`, etc. — check `wan_nodes` for which set is actually
  installed and build the graph from that set consistently, not a mix of both). **If
  `WanAnimateToVideo` (or another node whose name plainly indicates character/pose animation,
  e.g. containing "Animate" or "UniAnimate") is in `wan_nodes`, prefer it over a generic
  image-to-video node** — it's purpose-built for animating a subject rather than general
  video generation, which is a closer match to what this skill needs than a generic I2V node.
- If multiple families are present, prefer a dedicated character-animation entry point (like
  `WanAnimateToVideo` above) over a generic one, and otherwise prefer whichever produces a
  still-recognizable subject with natural motion at a small frame count — for a profile-picture
  GIF, simplicity and identity preservation matter more than production video quality.
- If you're unsure of a node's exact input schema from its name alone, note that in your report
  rather than guessing at inputs.

End the workflow with a `VHS_VideoCombine` node (`format: "image/gif"`, a reasonable `frame_rate`
like 8-12, `loop_count: 0`) instead of `SaveImage` — `has_video_combine` in the inventory
confirms this output node is installed; if it's false, there's no way to actually produce a GIF
from any family and you should stop and tell the orchestrator, same as the no-family case above.

**Do not reference any node class_type that isn't in the inventory's own lists
(`animatediff_nodes`/`ltxv_nodes`/`wan_nodes`) or the standard nodes already used in the
still-image workflow.** `scripts/check_config.py` now verifies every class_type your workflow references
against the server's live `/object_info` and will hard-error on anything not actually installed
— so inventing a plausible-sounding node name doesn't just risk a bad guess, it will be caught
and bounced back to you to fix.

**The subject must actually animate — this is not a camera-pan effect.** This is the entire
point of building a native workflow instead of accepting the synthetic fallback, so get this
right. `scripts/make_gif.py` already appends a motion clause to the prompt text before injection
(asking for gentle blinking, breathing, slight head movement — see `references/prompting.md`),
so you don't need to duplicate that in the workflow's static text nodes. But the *workflow's own
settings* also matter here, independent of the prompt text:

- **AnimateDiff**: prefer a general-purpose motion module over any motion LoRA whose name
  suggests it's specifically for camera moves (e.g. containing "PanLeft"/"PanRight"/"ZoomIn"/
  "ZoomOut"/"Dolly"/"Orbit") — those bias the whole clip toward camera movement over a static
  subject, which is exactly the failure mode this is meant to avoid. If only camera-motion LoRAs
  are available in the inventory, skip adding a motion LoRA rather than picking one of those.
  Keep `motion_scale` (or the equivalent strength input) modest — high values often produce more
  scene/camera movement rather than subtler subject animation.
- **LTX-Video**: apply the same principle even though the exact parameter names differ — if the
  node set exposes any explicit camera-motion/trajectory control, leave it at a neutral/static
  default rather than adding a pan/zoom/dolly, so the model's own motion prediction focuses on
  the subject instead of the frame.
- Whichever family: if the workflow supports a context/overlap/clip-length setting, keep it
  short (a few seconds) — this is a profile picture animation, not a video, and shorter/subtler
  is the goal.

## After writing the file(s)

Report back: the file path(s) you wrote, the checkpoint you used, any LoRAs picked (with a
one-line reason each), which animation family you targeted (AnimateDiff/LTX-Video/Wan2.x/none), and
whether a GIF workflow was produced. The orchestrating skill will validate your workflow by
running `scripts/check_config.py --backend comfyui --workflow <path>` (and `--gif-workflow
<path>` if applicable) — this checks both that titled nodes resolve correctly (most commonly
fixed by adding a missing `_meta.title` or fixing a broken node-id reference) AND that every
node class_type you referenced is actually installed on the live server (fixed by using only
node types that actually appear in the inventory's `animatediff_nodes`/`ltxv_nodes` lists, not
ones you assumed would be there). Fix whichever it reports and re-validate before generation.
