"""One shared TLS context for every outgoing httpx client.

Building a fresh `httpx.AsyncClient()` loads the CA bundle each time, which takes 2-3 seconds on this
Windows machine and blocks the event loop while it does (it froze the whole run for ~3s per page fetch and
per Jev call). Passing `verify=tls.context()` reuses one context, so a new client costs ~3ms.
"""

from __future__ import annotations

import ssl
import threading
from typing import Optional

_ctx: Optional[ssl.SSLContext] = None
_lock = threading.Lock()


def context() -> ssl.SSLContext:
    global _ctx
    if _ctx is None:
        with _lock:
            if _ctx is None:
                import certifi

                _ctx = ssl.create_default_context(cafile=certifi.where())
    return _ctx
