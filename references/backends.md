# Backend configuration

Config precedence (highest wins): CLI flag > environment variable > `./.claude/profile-gen.json`
> `~/.claude/profile-gen.json`. JSON config files use the snake_case keys below directly.

## ChatGPT (`--backend chatgpt`)

OpenAI Images API.

| Key | Env var | Default |
|---|---|---|
| `openai_api_key` | `OPENAI_API_KEY` | required |
| `openai_base_url` | `OPENAI_BASE_URL` | `https://api.openai.com` |
| `openai_image_model` | `OPENAI_IMAGE_MODEL` | `gpt-image-1` |

Request: `POST {base_url}/v1/images/generations` with `{model, prompt, n: 1, size: "{w}x{h}"}`.
When `--nsfw` is set, `"moderation": "low"` is added to the request body — this is the only
NSFW-specific behavior; the prompt text itself is unmodified (that's `prompt.py`'s job). Returns
base64-encoded PNG.

## Grok (`--backend grok`)

xAI Images API.

| Key | Env var | Default |
|---|---|---|
| `xai_api_key` | `XAI_API_KEY` | required |
| `xai_image_model` | `XAI_IMAGE_MODEL` | `grok-2-image` |

Request: `POST https://api.x.ai/v1/images/generations` with `{model, prompt, n: 1,
response_format: "b64_json"}`. This backend does not send `--width`/`--height` or a negative
prompt — xAI's docs also list `aspect_ratio`/`resolution`/`quality` request parameters this
backend doesn't currently use, should size control matter enough later to wire them up. Returns
JPEG (normalized to PNG on write-out when Pillow is available).

**Grok can and does return non-square images**, since it has no size control at all. This
backend reports `width=None, height=None` on the `ImageResult` rather than echoing back the
requested size as if it were real (a previous version did exactly that, which was simply false
and caused a real bug: a non-square Grok output labeled as square, then stretched when displayed
as a circular/square avatar downstream). `scripts/generate_image.py` is what actually decides
the real dimensions — it center-crops every generated image to square when Pillow is available,
regardless of backend, specifically so this can't happen again.

**No moderation/NSFW request parameter exists for this endpoint** — unlike ChatGPT's
`moderation: "low"`, xAI's image API has no request-level equivalent; the response only carries
a read-only `respect_moderation` field reporting whether the result passed. Getting a
non-refused result for legitimate NSFW requests is entirely a matter of prompt phrasing here —
see `references/prompting.md`'s NSFW clause section, which is backend-aware for exactly this
reason (`NSFW_CLAUSE_HOSTED` is used for this backend, not the blunt local-only clause).

## Grok CLI (`--backend grok-cli`)

No API key needed — this shells out to the locally-installed `grok` CLI (xAI's own agentic
coding-assistant CLI, `grok login` to authenticate) and uses its `/imagine`/`/imagine-video`
slash commands, billed against the user's Grok/X subscription usage rather than a separate xAI
API account. Use this when the user has a Grok subscription but no `XAI_API_KEY`.

| Key | Env var | Default |
|---|---|---|
| `grok_cli_bin` | `GROK_CLI_BIN` | `grok` (resolved via PATH) |
| `grok_cli_workdir` | `GROK_CLI_WORKDIR` | `~/.claude/profile-gen/grok-cli-runs` |
| `grok_cli_timeout_s` | `GROK_CLI_TIMEOUT_S` | `300` |

Mechanically different from the other backends — it runs `grok -p "/imagine <prompt>"
--output-format json --yolo` as a full agent turn (not a parameterized HTTP call) and parses the
resulting image path out of the CLI's own JSON response and session-directory layout. Real
consequences to know about:

- **No seed control**, and `--width`/`--height` are ignored (recorded in profile metadata, not
  sent to the CLI) — `/imagine` only takes a text description.
- **Costs real usage** on the user's account per call; the cost is reported back in the profile's
  `generation` metadata (`raw_meta.cost_usd`, surfaced by `check_config.py`/`generate_image.py`
  output) so the user can see what a run cost.
- **NSFW is still passed through in the prompt text** (using `NSFW_CLAUSE_HOSTED`, same as the
  direct Grok API — see `references/prompting.md`), but this goes through Grok's own agent loop,
  which likely shares the same underlying classifier as Grok Imagine's consumer "Spicy Mode" —
  that agent may apply its own judgment/guardrails around the request that this skill cannot
  force-override from outside, and blunt "no restrictions" phrasing is counterproductive here for
  the same reason it is on the direct API. Tell the user if a run comes back refused/hedged
  rather than retrying with a further-modified prompt.
- **GIF** (`--gif`) uses `/imagine-video` (plans shots, generates images, animates them) and
  converts the resulting video to GIF with `ffmpeg` (required on PATH for this path; falls back
  to the synthetic GIF otherwise, same as any other backend without native GIF support).
- Requires `grok` on PATH and already logged in (`grok login`, once, interactively — this skill
  does not manage that login).

## ComfyUI (`--backend comfyui`)

Fully generic — points at your own ComfyUI server and an exported API-format workflow. See
`references/comfyui.md` for the node-locating convention.

| Key | Env var | Default |
|---|---|---|
| `comfyui_url` | `COMFYUI_URL` | required |
| `comfyui_workflow` | `COMFYUI_WORKFLOW` | required (path to workflow JSON) |
| `comfyui_gif_workflow` | `COMFYUI_GIF_WORKFLOW` | optional (enables native GIF) |
| `comfyui_timeout_s` | `COMFYUI_TIMEOUT_S` | `600` |
| `comfyui_client_id` | `COMFYUI_CLIENT_ID` | random UUID per run |

## Mock (`--backend mock`)

No config required, no network calls. Draws a placeholder PNG with the prompt text and, when
`--nsfw` is set, a visible "NSFW" badge — used for offline testing of the whole pipeline including
the NSFW-flag plumbing.

## `check_config.py`

Run `python3 scripts/check_config.py --backend <name>` before spending any API calls. It validates
required keys are present (never prints raw secret values — only `<set>`/`<missing>`), and for
`comfyui` additionally checks server reachability (warning, not a hard error, if unreachable) and
dry-runs node resolution against the configured workflow(s), reporting which node IDs it found.
