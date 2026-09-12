# Voice reference

`voice` is **metadata only** — a plain string reference stored on the profile. profile-gen does
not synthesize or validate audio; it's left to whatever downstream app consumes the profile to
map the name to an actual voice (e.g. by passing it straight to a Kokoro TTS pipeline).

Any string is accepted. The list below is a convenience reference of commonly-used
[Kokoro TTS](https://github.com/hexgrad/kokoro) voice names, grouped by accent/gender, so you have
sensible options to offer when a run asks for one.

| Voice name | Accent | Gender |
|---|---|---|
| `af_heart` | American | female |
| `af_bella` | American | female |
| `af_jessica` | American | female |
| `af_nicole` | American | female |
| `af_sarah` | American | female |
| `am_adam` | American | male |
| `am_michael` | American | male |
| `am_liam` | American | male |
| `bf_emma` | British | female |
| `bf_alice` | British | female |
| `bm_george` | British | male |
| `bm_daniel` | British | male |

These are suggestions, not a closed set — pass any string that means something to your
downstream TTS pipeline.
