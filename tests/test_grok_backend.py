import base64
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from profilegen.backends.base import PromptSpec
from profilegen.backends.grok import GrokBackend


def test_generate_image_reports_none_dimensions_not_the_requested_size():
    """Regression test: Grok's API ignores width/height entirely and can return any aspect
    ratio. Previously this backend echoed back spec.width/spec.height as if they were the real
    output size, which was simply false and caused a real bug -- a non-square Grok image
    labeled as square, then stretched wherever it was displayed as a square/circular avatar.
    """
    fake_bytes = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
    fake_response = {"data": [{"b64_json": base64.b64encode(fake_bytes).decode("ascii")}]}

    with patch("profilegen.backends.grok.http.json_post", return_value=fake_response):
        backend = GrokBackend({"xai_api_key": "sk-test"})
        result = backend.generate_image(PromptSpec(positive="a person", width=1024, height=1024))

    assert result.data == fake_bytes
    assert result.format == "jpeg"
    assert result.width is None
    assert result.height is None
