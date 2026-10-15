"""Kept for the agents: a thin wrapper over app.modal_client (Modal -> cache -> fallback).

    result, used_fallback = await call("score_fit", dna, portfolio, 50, fallback=cached)

Never raises and never hangs. For richer results (source, reason, offline data shaped like the contract)
use `app.modal_client.similar_companies / score_fit / backtest` directly.
"""

from __future__ import annotations

from typing import Any

from .. import modal_client as _mc


def configured() -> bool:
    return _mc.configured()


async def call(fn_name: str, *args: Any, fallback: Any = None, timeout: float | None = None,
               **kwargs: Any) -> tuple[Any, bool]:
    """Returns (result, used_fallback). A cached earlier Modal answer beats `fallback`."""
    return await _mc.call_pair(fn_name, *args, fallback=fallback, timeout=timeout, **kwargs)
