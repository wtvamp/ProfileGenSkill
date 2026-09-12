#!/usr/bin/env python3
"""A tiny fake ComfyUI HTTP server for offline testing of the ComfyUI backend.

Endpoints:
  GET  /system_stats          -> 200 {}
  GET  /object_info            -> 200 {<class_type>: {...}} for a small fixed set of node
                                  types (the ones tests/fixtures/*.api.json actually use) --
                                  used to test check_config.py's live node-existence check
  POST /prompt                -> 200 {"prompt_id": "test-123"}
  GET  /history/test-123      -> 200 {"test-123": {"outputs": {"9": {"images": [...]}}}}
  GET  /view?...              -> 200 image bytes (Content-Type: image/png)
"""
from __future__ import annotations

import json
import struct
import threading
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

PROMPT_ID = "test-123"


def _fixture_png() -> bytes:
    width, height = 8, 8

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = bytearray()
    for _ in range(height):
        raw.append(0)
        for _ in range(width):
            raw.extend((100, 150, 200))
    compressed = zlib.compress(bytes(raw), level=6)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


FIXTURE_PNG = _fixture_png()

# Only the node types tests/fixtures/*.api.json actually reference -- deliberately does NOT
# include any AnimateDiff/LTX-Video node, so a workflow referencing one of those (or anything
# else not listed here) exercises check_config.py's live node-existence check correctly.
OBJECT_INFO = {
    class_type: {"input": {"required": {}}}
    for class_type in (
        "CheckpointLoaderSimple",
        "CLIPTextEncode",
        "EmptyLatentImage",
        "KSampler",
        "KSamplerAdvanced",
        "VAEDecode",
        "SaveImage",
        "VHS_VideoCombine",
    )
}


class MockComfyUIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002
        pass

    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/system_stats":
            self._send_json({})
        elif parsed.path == "/object_info":
            self._send_json(OBJECT_INFO)
        elif parsed.path == f"/history/{PROMPT_ID}":
            self._send_json(
                {
                    PROMPT_ID: {
                        "outputs": {
                            "9": {
                                "images": [
                                    {"filename": "fixture.png", "subfolder": "", "type": "output"}
                                ]
                            }
                        }
                    }
                }
            )
        elif parsed.path == "/view":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(FIXTURE_PNG)))
            self.end_headers()
            self.wfile.write(FIXTURE_PNG)
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        _ = self.rfile.read(length)
        if parsed.path == "/prompt":
            self._send_json({"prompt_id": PROMPT_ID})
        else:
            self._send_json({"error": "not found"}, status=404)


def start_server(port: int = 0):
    server = HTTPServer(("127.0.0.1", port), MockComfyUIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8188
    server, thread = start_server(port)
    print(f"Mock ComfyUI server listening on http://127.0.0.1:{server.server_port}")
    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()
