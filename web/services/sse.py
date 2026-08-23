"""Server-Sent Events framing.

Every event's ``data:`` is a single-line JSON object. This is not a style
choice: a raw token containing a newline would be framed as two ``data:``
lines and silently rejoined with a newline the model never emitted.
JSON-encoding guarantees one line, always.
"""

from __future__ import annotations

import json
from typing import Any


def sse(event: str, data: dict[str, Any]) -> bytes:
    """Format one SSE frame.

    Returns bytes, not str. With ``direct_passthrough`` set (see sse_headers)
    Werkzeug hands the iterable straight to the WSGI server, which asserts
    ``applications must write bytes`` — and the failure mode is a 200 with
    correct headers and an empty body, which the Flask test client does not
    reproduce because it encodes on the way out.
    """
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode()


def ping() -> bytes:
    """A comment frame. Keeps proxies from closing an idle connection while
    the model is still thinking."""
    return b": ping\n\n"


def sse_headers(response) -> None:
    """Apply the headers required for a stream to actually stream."""
    response.headers["Content-Type"] = "text/event-stream; charset=utf-8"
    response.headers["Cache-Control"] = "no-cache, no-transform"
    # nginx buffers proxied responses by default, which would hold the whole
    # answer until completion and defeat the entire feature.
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    # Stops Werkzeug from buffering or re-encoding the iterator.
    response.direct_passthrough = True
