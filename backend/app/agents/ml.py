"""The agents' view of the model: Modal first, the local dataset scorer as the fallback.

The Modal wrappers (`similar_companies(query, k)`, `score_fit(fund_dna, portfolio, k)`) live in
app/modal_client.py (written by the Modal track; app/tools/modal_client.py is checked first). They return a
`ModalResult(value, source, reason)`; plain dicts and `(result, used_fallback)` tuples are accepted too.
Only answers the model computed (source "modal" or "cache") are used, and only results that map to real
dataset rows; otherwise this falls back to `app.tools.dataset`, and the feed says so.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
from typing import Any, Optional

from .. import config
from ..tools import dataset

log = logging.getLogger("bellwether.ml")


def _modal_fn(name: str):
    for mod_name in ("app.tools.modal_client", "app.modal_client"):
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    return None


async def _call_modal(name: str, *args: Any, **kwargs: Any) -> Optional[Any]:
    """Result of the Modal wrapper, or None when it isn't there, timed out, errored or used its fallback."""
    fn = _modal_fn(name)
    if fn is None:
        return None
    try:
        res = fn(*args, **kwargs)
        if inspect.isawaitable(res):  # the wrapper has its own timeout; this is only a safety net
            res = await asyncio.wait_for(res, timeout=config.modal_timeout_s() + 10)
    except Exception as exc:
        log.warning("modal %s failed: %s", name, type(exc).__name__)
        return None
    if hasattr(res, "value") and hasattr(res, "source"):  # app.modal_client.ModalResult
        # Only answers the model computed (now, or earlier and cached) count; otherwise use our fallback,
        # which says so in the feed.
        return res.value if res.source in ("modal", "cache") else None
    if isinstance(res, tuple) and len(res) == 2 and isinstance(res[1], bool):
        res, used_fallback = res
        if used_fallback:
            return None
    return res


async def warm_up() -> None:
    """Start both model containers at run start (a cold start is ~10-20s each) so the Mapper's and Deal Finder's
    calls find them warm: a tiny similar_companies query and an empty score_fit, at the same time.
    Fire-and-forget: never raises, caches nothing."""
    try:
        from .. import modal_client as mc
        if mc.configured() and not mc.disabled():
            await asyncio.gather(mc.call("similar_companies", "warm up", 1, timeout=90.0, use_cache=False),
                                 mc.call("score_fit", {}, [], 1, timeout=90.0, use_cache=False),
                                 return_exceptions=True)
    except Exception:
        log.info("modal warm-up skipped")


def _items(res: Any) -> list[dict]:
    if isinstance(res, list):
        return [r for r in res if isinstance(r, dict)]
    if isinstance(res, dict):
        for key in ("results", "items", "candidates", "top", "scores"):
            if isinstance(res.get(key), list):
                return [r for r in res[key] if isinstance(r, dict)]
    return []


def _row_for(item: dict) -> Optional[dict]:
    for key in ("company_id", "id"):
        if item.get(key):
            r = dataset.get(str(item[key]))
            if r:
                return r
    if item.get("row_id") is not None:
        return dataset.get(int(item["row_id"]))
    return None


async def similar(query_row: Optional[dict], text: str, k: int = 8,
                  exclude: list[str] | None = None) -> tuple[list[tuple[dict, float]], str]:
    """Companies like a portfolio company. Returns ([(row, score)], "model" | "dataset")."""
    exclude = exclude or []
    query = query_row["id"] if query_row else text
    res = await _call_modal("similar_companies", query, k + len(exclude))
    out: list[tuple[dict, float]] = []
    for item in _items(res):
        r = _row_for(item)
        if r and r["id"] not in exclude and (not query_row or r["id"] != query_row["id"]):
            out.append((r, float(item.get("score") or 0.0)))
    if len(out) >= min(3, k):
        return out[:k], "model"
    local = await asyncio.to_thread(dataset.similar, query_row or text, k, exclude)
    return local, "dataset"


_PART_ALIASES = {"Like the portfolio": ("like_portfolio", "similarity", "portfolio", "like"),
                 "Right stage": ("stage",), "Right location": ("geo", "location", "country")}


def _parts(item: dict) -> dict[str, float]:
    raw = item.get("parts") or item.get("contributions") or item.get("fit_parts") or {}
    if isinstance(raw, list):
        raw = {str(p.get("label")): p.get("value") for p in raw if isinstance(p, dict)}
    out: dict[str, float] = {}
    for label, keys in _PART_ALIASES.items():
        for k_, v in raw.items():
            if k_ == label or any(a in k_.lower() for a in keys):
                try:
                    out[label] = round(max(0.0, min(1.0, float(v))), 2)
                except (TypeError, ValueError):
                    pass
                break
    return out


async def score(dna: dict, portfolio_rows: list[dict], k: int = 50, *,
                sector_weights: dict[str, float] | None = None,
                exclude: list[str] | None = None) -> tuple[list[dict], dict[int, int], str]:
    """Top-k candidates for the fund. Returns (candidates, {row_id: fit} for the Universe page, source).

    Candidates are {"row", "fit", "parts", "like"} (see dataset.score). source is "model" or "dataset".
    """
    portfolio = [dataset.brief(r) for r in portfolio_rows]
    res = await _call_modal("score_fit", dna, portfolio, k)
    cands: list[dict] = []
    skip = set(exclude or []) | {r["id"] for r in portfolio_rows}
    for item in _items(res):
        r = _row_for(item)
        if not r or r["id"] in skip:
            continue
        try:  # "fit" is 0..100; "score" alone is 0..1
            if item.get("fit") is not None:
                fit_i = int(round(float(item["fit"])))
            else:
                fit_i = int(round(float(item["score"]) * 100))
        except (KeyError, TypeError, ValueError):
            continue
        like = dataset.get(str(item.get("like") or item.get("similar_to") or "")) if (
            item.get("like") or item.get("similar_to")) else None
        cands.append({"row": r, "fit": max(0, min(99, fit_i)), "parts": _parts(item), "like": like})
    if len(cands) >= min(10, k):
        cands.sort(key=lambda c: -c["fit"])
        # The Universe still gets every row's fit from the local scorer (cheap, and the page needs all rows).
        _, all_scores = await asyncio.to_thread(dataset.score, dna, portfolio_rows, 1,
                                                sector_weights=sector_weights, exclude=list(skip))
        for c in cands:
            all_scores[c["row"]["row_id"]] = c["fit"]
        return cands[:k], all_scores, "model"
    top, all_scores = await asyncio.to_thread(dataset.score, dna, portfolio_rows, k,
                                              sector_weights=sector_weights, exclude=list(skip))
    return top, all_scores, "dataset"
