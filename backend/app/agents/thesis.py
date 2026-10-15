"""Thesis: turns what Reader found into the fund's DNA (FundDNA), with evidence.

Model: the worker model (MODEL_WORKER). Fallback: a simpler thesis computed from the portfolio's sector counts.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from pydantic import BaseModel

from .. import data, store
from ..models import Fund, FundDNA, SectorShare, Source
from ..tools import dataset, web
from .context import RunContext, plan
from .llm import WORKER_MODEL, LLMError, LLMUnavailable, dumps
from .reader import ReaderResult, portfolio_brief

PALETTE = ["#D3AD5E", "#B4532A", "#7FA3C0", "#5C7A63", "#A3BBA6", "#9A958B"]


class SectorCount(BaseModel):
    name: str
    count: int


class Evidence(BaseModel):
    text: str
    source_url: Optional[str] = None


class ThesisDraft(BaseModel):
    summary: str
    stage: str
    geo: str
    cheque: str
    sectors: list[SectorCount]
    themes: list[str]
    evidence: list[Evidence]


SYSTEM = (
    "You are Thesis, part of Bellwether, a research assistant for a venture capital fund. From what the fund "
    "says about itself and what it has backed, you write its investment thesis in plain English that a "
    "non-expert understands. Base every statement on the material given; when something isn't stated, say "
    "'Not stated' rather than inventing it. Never use or infer founders' gender, age, ethnicity or "
    "nationality. " + web.UNTRUSTED_RULES
)


def _sector_shares(counts: list[tuple[str, int]], limit: int = 5) -> list[SectorShare]:
    counts = [(n, c) for n, c in counts if c > 0]
    counts.sort(key=lambda t: -t[1])
    top = counts[:limit]
    total = sum(c for _, c in counts) or 1
    return [SectorShare(name=n, count=c, share=round(c / total, 2), color=PALETTE[i % len(PALETTE)])
            for i, (n, c) in enumerate(top)]


def fallback_dna(reader: ReaderResult) -> FundDNA:
    counts = Counter(p.company.sector for p in reader.portfolio if p.company.sector not in ("", "Other"))
    sectors = _sector_shares(list(counts.items()), limit=4)
    names = ", ".join(s.name.lower() for s in sectors[:3]) or "a mix of sectors"
    return FundDNA(summary=f"Has backed {len(reader.portfolio)} companies, mostly {names}.",
                   stage=reader.stage_hint or "Not stated", geo=reader.geo_hint or "Not stated",
                   cheque=reader.cheque_hint or "Not stated", sectors=sectors,
                   themes=[s.name for s in sectors[:3]], sources=reader.pages_read[:3])


async def run(ctx: RunContext, reader: ReaderResult) -> FundDNA:
    emit = ctx.emit
    name = reader.fund_name
    emit.step("Thesis", f"Reading what {name} has backed so far.", **plan("thesis", "working"))
    previous = store.get_memory(ctx.fund_id, "fund_dna")  # "what you knew last time"
    weights = store.get_memory(ctx.fund_id, "thesis_weights", {}) or {}

    prompt = (
        f"Fund: {name} ({reader.fund_url})\n"
        f"What the fund says it invests in (from its website):\n"
        f"{web.wrap_untrusted(reader.fund_url, reader.stated_focus or 'Nothing stated.', 3000)}\n"
        f"Hints from the website: stage={reader.stage_hint!r}, cheque={reader.cheque_hint!r}, geo={reader.geo_hint!r}\n"
        f"Blog topics: {dumps(reader.blog_topics)}\n"
        f"Portfolio ({len(reader.portfolio)} companies): {portfolio_brief(reader)}\n"
        f"Sources you may cite (URLs): {dumps([s.url for s in reader.pages_read if s.url])}\n"
        f"Use these sector names where they fit: {dumps(dataset.sector_labels()[:26])}\n"
        + (f"Last time you wrote this thesis: {dumps(previous)}. Keep it unless the new material changes it.\n"
           if previous else "")
        + (f"The partners' feedback so far nudged these sectors (+ = more interest): {dumps(weights)}\n"
           if weights else "")
        + "\nWrite: a one-sentence summary (e.g. 'Backs very early founders in the UK and Europe, mostly fintech, "
          "health and deep tech.'); the stage (e.g. 'Pre-seed & Seed'); the geography (e.g. 'UK & Europe'); the "
          "typical first cheque (e.g. '£0.5M – £2M', or 'Not stated'); 3 to 5 sectors with how many portfolio "
          "companies are in each; 3 to 5 short themes; and 2 to 4 pieces of evidence, each with the source URL."
    )
    try:
        draft = await ctx.llm.json(model=WORKER_MODEL, effort="medium", system=SYSTEM, prompt=prompt,
                                   schema=ThesisDraft, on_retry=ctx.retry_hook("Thesis", "writing the thesis"))
        sources = [Source(label=web.host_of(e.source_url) or "website", url=e.source_url)
                   for e in draft.evidence if e.source_url][:4] or reader.pages_read[:3]
        dna = FundDNA(summary=draft.summary.strip(), stage=draft.stage, geo=draft.geo, cheque=draft.cheque,
                      sectors=_sector_shares([(s.name, s.count) for s in draft.sectors]),
                      themes=[t.strip() for t in draft.themes if t.strip()][:5], sources=sources)
    except LLMUnavailable:
        raise
    except LLMError:
        dna = fallback_dna(reader)
        emit.recovered("Thesis", "Couldn't write the full thesis, so I built a simpler one from the portfolio.",
                       fallback="portfolio counts")

    if dna.sectors:
        top = dna.sectors[0]
        emit.step("Thesis", f"Grouped the portfolio by sector. {top.name} is the biggest group, "
                  f"with {top.count} {'company' if top.count == 1 else 'companies'}.")
    if dna.stage != "Not stated" or dna.cheque != "Not stated":
        emit.step("Thesis", f"Most first cheques are {dna.stage.lower()}"
                  + (f", between {dna.cheque}." if dna.cheque not in ("", "Not stated") else "."))
    emit.finding("Thesis", dna.summary, **plan("thesis", "done"))

    fund = data.get_fund(ctx.fund_id, reader.fund_url)
    domain = web.host_of(reader.fund_url)
    fund = Fund(id=ctx.fund_id, name=name, url=reader.fund_url,
                logo=fund.logo or (f"https://www.google.com/s2/favicons?domain={domain}&sz=128" if domain else None),
                dna=dna)
    data.save_page(ctx.fund_id, "fund", fund)
    store.set_memory(ctx.fund_id, "fund_dna", dna.model_dump(mode="json"))
    return dna
