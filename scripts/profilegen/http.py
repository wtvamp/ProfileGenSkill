"""Thin urllib.request-based HTTP wrapper. Stdlib only, no third-party dependency."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .backends.base import BackendError

DEFAULT_TIMEOUT = 60


def _urlopen(req: urllib.request.Request, timeout: float):
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise BackendError(f"HTTP {e.code} from {req.full_url}: {body}") from e
    except urllib.error.URLError as e:
        raise BackendError(f"Connection error to {req.full_url}: {e.reason}") from e
    except OSError as e:
        raise BackendError(f"Connection error to {req.full_url}: {e}") from e


def json_post(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    data = json.dumps(body).encode("utf-8")
    req_headers = {"Content-Type": "application/json", **headers}
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    with _urlopen(req, timeout) as resp:
        raw = resp.read()
        status = resp.getcode()
    if status < 200 or status >= 300:
        raise BackendError(f"HTTP {status} from {url}: {raw.decode('utf-8', errors='replace')}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise BackendError(f"Invalid JSON response from {url}: {e}") from e


def get_bytes(url: str, headers: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    with _urlopen(req, timeout) as resp:
        raw = resp.read()
        status = resp.getcode()
    if status < 200 or status >= 300:
        raise BackendError(f"HTTP {status} from {url}")
    return raw


def get_json(url: str, headers: dict[str, str] | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict:
    raw = get_bytes(url, headers, timeout)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise BackendError(f"Invalid JSON response from {url}: {e}") from e
