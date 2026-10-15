"""Enricher: fills in company profiles that the 10k dataset doesn't have (mostly the fund's own portfolio).

For each company it reads, at the same time, the fund's page about it (<fund>/companies/<slug>) and the
company's own website, screens both for text aimed at an AI (RunContext.screen_page), and asks the cheap
extract model (MODEL_EXTRACT) for a short profile. Results are stored per company in SQLite memory
(`enrich:<company_id>`) and merged into GET /api/companies/{id} and /detail by app.data / app.company_detail.

The work is split across several workers ("Enricher #1", "#2", ...) that run in parallel, sharing one limit
of ~16 open pages/model calls at a time. Progress goes to the feed every batch.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Iterable, Optional

from pydantic import BaseModel

from .. import config, store
from ..models import Company
from ..tools import web
from .context import RunContext
from .llm import EXTRACT_MODEL, LLMError, LLMUnavailable

log = logging.getLogger("bellwether.enricher")

AGENT = "Enricher"
CONCURRENCY = 16
WORKERS = 8
BATCH = 25  # a progress line every this many companies
PAGE_CHARS = 6000


class Profile(BaseModel):
    one_liner: Optional[str] = None
    description: Optional[str] = None
    sector: Optional[str] = None
    stage: Optional[str] = None
    country: Optional[str] = None
    founded: Optional[int] = None
    business_model: Optional[str] = None
    customers: Optional[str] = None
    website: Optional[str] = None


SYSTEM = (
    "You fill in a short factual profile of one startup for a venture capital analyst, using only the pages "
    "given. Plain English, no hype. one_liner: under 12 words. description: 2-3 sentences. stage: e.g. "
    "'Seed', 'Series A', 'Acquired', 'Public' only if the pages say so. founded: a year. Leave a field null "
    "when the pages don't say. " + web.UNTRUSTED_RULES
)


def needs_enrichment(c: Company) -> bool:
    return c.row_id is None


def get(fund_id: str, company_id: str) -> Optional[dict]:
    return store.get_memory(fund_id, f"enrich:{company_id}")


def all_for(fund_id: str) -> dict[str, dict]:
    return {k.split(":", 1)[1]: v for k, v in store.list_memory(fund_id, "enrich:").items()}


def _fund_page(fund_url: str, c: Company) -> str:
    return f"{fund_url.rstrip('/')}/companies/{c.id}"


async def _read(ctx: RunContext, url: str) -> Optional[web.Page]:
    try:
        page = await web.fetch_page(url)
    except web.FetchError:
        return None
    except Exception:  # one page never stops the rest
        log.exception("enrich fetch failed: %s", url)
        return None
    await ctx.screen_page(AGENT, page)
    return page


async def _search(ctx: RunContext, c: Company, sem: asyncio.Semaphore) -> Optional[tuple[str, list[dict]]]:
    """Fallback when no page could be read: a short Claude web search (results are untrusted text)."""
    async with sem:
        try:
            out = await ctx.llm.search(
                model=EXTRACT_MODEL, effort="low", max_uses=2, max_tokens=2000, max_continuations=1,
                system="Find public facts about one startup. " + web.UNTRUSTED_RULES,
                prompt=(f"Find the startup {c.name!r} (a portfolio company of {ctx.fund_name}). Report what it "
                        "does, sector, stage, country, founding year, business model, customers and website."))
        except LLMUnavailable:
            raise
        except LLMError:
            return None
    urls = list(dict.fromkeys([q["url"] for q in out.quotes if q.get("url")] + [h.url for h in out.hits]))[:4]
    if not out.text.strip() or not urls:
        return None
    return (web.wrap_untrusted(urls[0], out.text, limit=PAGE_CHARS, label="untrusted_source"),
            [{"label": web.host_of(u), "url": u} for u in urls])


async def enrich_one(ctx: RunContext, fund_url: str, c: Company, sem: asyncio.Semaphore) -> bool:
    """Read both pages concurrently and store a profile. True when something was filled in."""
    urls = [_fund_page(fund_url, c)]
    if c.website:
        urls.append(c.website if "://" in c.website else f"https://{c.website}")
    async with sem:
        pages = [p for p in await asyncio.gather(*(_read(ctx, u) for u in urls)) if p and p.text.strip()]
    sources = [{"label": web.host_of(p.final_url), "url": p.final_url} for p in pages]
    body = "\n\n".join(web.wrap_untrusted(p.final_url, p.text, limit=PAGE_CHARS) for p in pages)
    if not pages:  # no fund page and no known website: one quick web search instead
        found = await _search(ctx, c, sem)
        if found is None:
            return False
        body, sources = found
    async with sem:
        try:
            prof = await ctx.llm.json(model=EXTRACT_MODEL, effort="low", system=SYSTEM, schema=Profile,
                                      max_tokens=1200,
                                      prompt=f"Company: {c.name}\nKnown so far: {c.model_dump_json()}\n\n{body}")
        except LLMUnavailable:
            raise
        except LLMError:
            return False
    out = {k: v for k, v in prof.model_dump().items() if v not in (None, "")}
    if not out:
        return False
    out["sources"] = sources
    store.set_memory(ctx.fund_id, f"enrich:{c.id}", out)
    return True


async def run(ctx: RunContext, fund_url: str, companies: Iterable[Company], *, what: str = "portfolio",
              force: bool = False) -> dict[str, int]:
    """Enrich every company that lacks data, across WORKERS parallel workers. Returns {"filled", "total"}."""
    emit = ctx.emit
    seen: set[str] = set()
    todo = []
    for c in companies:
        if c.id in seen or not needs_enrichment(c):
            continue
        seen.add(c.id)
        if force or get(ctx.fund_id, c.id) is None:
            todo.append(c)
    total = len(todo)
    if not total:
        return {"filled": 0, "total": 0}
    n_workers = max(1, min(WORKERS, (total + 9) // 10))
    chunks = [todo[i::n_workers] for i in range(n_workers)]
    emit.step(AGENT, f"Splitting {total} {what} companies across {n_workers} Enricher workers running in "
              "parallel. Each reads the fund's page and the company's own site.", workers=n_workers, total=total)
    sem = asyncio.Semaphore(min(CONCURRENCY, config.cap("enrich_concurrency")))  # RUN_PROFILE
    state = {"done": 0, "filled": 0}

    async def one(c: Company) -> None:
        ok = False
        try:
            ok = await enrich_one(ctx, fund_url, c, sem)
        except LLMUnavailable:
            raise
        except Exception:
            log.exception("enrich failed: %s", c.id)
        state["done"] += 1
        state["filled"] += ok
        if state["done"] % BATCH == 0 and state["done"] < total:
            emit.finding(AGENT, f"Filled profiles for {state['filled']} of {total} companies so far.", tag=None,
                         filled=state["filled"], total=total)

    async def worker(i: int, chunk: list[Company]) -> None:
        emit.step(AGENT, f"Enricher #{i} started on {len(chunk)} companies.", worker=i, workers=n_workers)
        await asyncio.gather(*(one(c) for c in chunk))
        emit.step(AGENT, f"Enricher #{i} finished its {len(chunk)} companies.", worker=i, workers=n_workers)

    await asyncio.gather(*(worker(i + 1, ch) for i, ch in enumerate(chunks)))
    emit.finding(AGENT, f"Filled profiles for {state['filled']} of {total} {what} companies.", tag=None,
              filled=state["filled"], total=total)
    emit.done(AGENT, "Finished filling in company profiles.")
    return {"filled": state["filled"], "total": total}


class LogEmitter:
    """For runs outside a live run (POST /api/funds/{id}/enrich): events go to the server log."""

    def __getattr__(self, name: str) -> Any:
        def log_event(agent: str, message: str = "", *a: Any, **k: Any) -> None:
            log.info("%s %s: %s", name, agent, message)
        return log_event
