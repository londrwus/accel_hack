"""In-memory cache of rendered page responses (JSON bytes), keyed by (endpoint, fund, params).

Any write to the memory table (a run saving results, feedback, watch, enrichment) clears it, so pages are never
stale for long; a short TTL also lets background logo fetches show up."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Hashable

TTL = 600.0
_lock = threading.Lock()
_cache: dict[Hashable, tuple[float, bytes]] = {}


def clear() -> None:
    with _lock:
        _cache.clear()


def get(key: Hashable) -> bytes | None:
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < TTL:
        return hit[1]
    return None


def put(key: Hashable, body: bytes) -> bytes:
    with _lock:
        _cache[key] = (time.monotonic(), body)
    return body


def render(key: Hashable, build: Callable[[], Any]) -> bytes:
    body = get(key)
    if body is None:
        model = build()
        body = put(key, model.model_dump_json().encode() if hasattr(model, "model_dump_json") else model)
    return body
