"""Give every Company / GraphNode / Fund in an API response the best logo we have (app/tools/logos.py).

Fast: dictionary lookups and a cached index only. Missing site logos are fetched in the background and show up
on the next page load. Mock paths ("/logos/x.png") and made-up demo companies (no website, not in the dataset)
are left alone.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import BaseModel

from .models import Company, Fund, GraphNode
from .tools import logos

_GOOGLE = "https://www.google.com/s2/favicons"


def _improvable(logo: str | None) -> bool:
    return not logo or logo.startswith(_GOOGLE)


def fill(obj: Any, fetch: bool = True) -> Any:
    """Walks models, lists and dicts in place and returns `obj`."""
    try:
        _walk(obj, fetch, {})
    except Exception:  # never break a page over a logo
        logos.log.exception("logo fill failed")
    return obj


@lru_cache(maxsize=1)
def _made_up_ids() -> frozenset[str]:
    """Made-up demo companies (in the mocks with no logo). They always keep an initial tile."""
    from . import data

    ids: set[str] = set()
    for name in ("deals", "portfolio", "map", "memos", "memo", "universe"):
        try:
            raw = data.mock(name).model_dump()
        except Exception:
            continue
        stack = [raw]
        while stack:
            x = stack.pop()
            if isinstance(x, dict):
                if "one_liner" in x and "id" in x and not x.get("logo"):
                    ids.add(x["id"])
                if x.get("kind") in ("pick", "portfolio", "competitor") and not x.get("logo"):
                    ids.add(x.get("company_id") or x.get("id"))
                stack.extend(x.values())
            elif isinstance(x, list):
                stack.extend(x)
    return frozenset(i for i in ids if i)


def _walk(obj: Any, fetch: bool, by_id: dict[str, str | None]) -> None:
    if isinstance(obj, Company):
        if obj.id in _made_up_ids():
            return
        if _improvable(obj.logo):
            # A Google favicon URL 404s for unknown domains (a broken image + console error): replace it with the
            # cached file once fetched, else an initial tile.
            obj.logo = logos.resolve(obj.name, obj.website, obj.row_id, obj.id, fetch=fetch, sector=obj.sector)
        by_id[obj.id] = obj.logo
        return
    if isinstance(obj, Fund):
        if _improvable(obj.logo):
            obj.logo = logos.resolve(None, obj.url, fetch=fetch)
        return
    if isinstance(obj, GraphNode):
        if _improvable(obj.logo) and obj.kind != "fund" and (obj.company_id or obj.id) not in _made_up_ids():
            if obj.company_id and obj.company_id in by_id:
                obj.logo = by_id[obj.company_id]
            else:
                domain = obj.logo.split("domain=")[1].split("&")[0] if obj.logo and "domain=" in obj.logo else None
                obj.logo = logos.resolve(obj.label, domain, None, obj.company_id, fetch=fetch)
        return
    if isinstance(obj, BaseModel):
        # Companies first (shortlists etc.) so graph nodes can reuse their logos.
        fields = sorted(type(obj).model_fields, key=lambda f: f == "nodes")
        for name in fields:
            _walk(getattr(obj, name), fetch, by_id)
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            _walk(x, fetch, by_id)
    elif isinstance(obj, dict):
        for x in obj.values():
            _walk(x, fetch, by_id)


def prewarm() -> None:
    """Queue logo fetches for every company on the saved pages (all funds with runs), so logos are there on first view."""
    import threading

    def job() -> None:
        from . import data, store

        funds = {r["fund_id"] for r in store.list_runs(limit=200)}
        for fid in funds:
            for load in (data.deals, data.portfolio, data.market_map):
                try:
                    fill(load(fid))
                except Exception:
                    pass

    threading.Thread(target=job, name="logo-prewarm", daemon=True).start()
