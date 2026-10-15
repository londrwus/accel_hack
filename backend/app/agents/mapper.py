"""Mapper: who each portfolio company competes with, drawn as the Market Map.

1. `find_competitors`: for up to 6 portfolio companies, ask the model for "companies like this"
   (Modal similar_companies, fallback: dataset word overlap), then the worker model keeps the real competitors.
2. `build_map`: once Deal Finder has picks, lay out nodes/edges on the 800x780 design canvas and save the page.
"""

from __future__ import annotations

import asyncio
import math
from typing import Optional

from pydantic import BaseModel, Field

from .. import config, data
from ..models import Company, DealFlowItem, GraphEdge, GraphNode, MapResponse
from ..tools import dataset
from . import ml
from .context import RunContext, plan
from .llm import WORKER_MODEL, LLMError, LLMUnavailable, dumps
from .reader import ReaderResult

MAX_PORTFOLIO_NODES = 6
MAX_COMPETITORS_EACH = 2


class CompetitorPick(BaseModel):
    portfolio_id: str
    competitor_ids: list[str]


class CompetitorPicks(BaseModel):
    items: list[CompetitorPick]


class MapperResult(BaseModel):
    portfolio: list[Company] = Field(default_factory=list)
    competitors: dict[str, list[Company]] = Field(default_factory=dict)  # portfolio id -> competitors
    source: str = "dataset"


SYSTEM = (
    "You are Mapper, part of Bellwether, a research assistant for a venture capital fund. You decide which "
    "companies really compete with a portfolio company: same customers and a similar product. Similar words "
    "are not enough. Pick only from the candidates given, by id."
)


def _pick_portfolio(reader: ReaderResult) -> list[tuple[Company, Optional[dict]]]:
    """Up to 6 active portfolio companies, preferring ones we have data on, spread across sectors."""
    active = [p for p in reader.portfolio if not p.exited]
    active.sort(key=lambda p: (not p.in_dataset, not p.company.one_liner))
    chosen, sectors = [], set()
    for p in active:  # one per sector first, so the map shows the range
        if p.company.sector not in sectors:
            chosen.append(p)
            sectors.add(p.company.sector)
        if len(chosen) >= MAX_PORTFOLIO_NODES:
            break
    for p in active:
        if len(chosen) >= MAX_PORTFOLIO_NODES:
            break
        if p not in chosen:
            chosen.append(p)
    return [(p.company, dataset.get(p.company.id) if p.in_dataset else None) for p in chosen]


async def find_competitors(ctx: RunContext, reader: ReaderResult) -> MapperResult:
    emit = ctx.emit
    emit.step("Mapper", "Looking up competitors for each portfolio company.", **plan("map", "working"))
    picked = _pick_portfolio(reader)
    portfolio_ids = [p.company.id for p in reader.portfolio]
    candidates: dict[str, list[tuple[dict, float]]] = {}
    sources = set()
    # All look-ups at once (the model answers in under a second each once it is warm).
    sem = asyncio.Semaphore(max(1, config.cap("mapper_concurrency")))

    async def look_up(company: Company, row: Optional[dict]) -> tuple[list[tuple[dict, float]], str]:
        async with sem:
            emit.tool("Mapper", "similar_companies", f"Asking the model for companies like {company.name}.",
                      company_id=company.id)
            return await ml.similar(row, f"{company.name}. {company.one_liner}", k=8, exclude=portfolio_ids)

    found = await asyncio.gather(*(look_up(company, row) for company, row in picked))
    for (company, _row), (sims, src) in zip(picked, found):
        sources.add(src)
        candidates[company.id] = sims
    if "dataset" in sources and dataset.size():
        emit.recovered("Mapper", "The similarity model on Modal didn't answer, so I matched companies by "
                       "what they do in the dataset.", fallback="dataset")

    chosen: dict[str, list[str]] = {}
    if any(candidates.values()):
        listing = {cid: [{"id": r["id"], "name": r["name"], "what": r["one_liner"][:140],
                          "sector": r["sector_label"]} for r, _ in sims]
                   for cid, sims in candidates.items()}
        about = {c.id: f"{c.name}: {c.one_liner[:160]}" for c, _ in picked}
        try:
            res = await ctx.llm.json(
                model=WORKER_MODEL, effort="low", system=SYSTEM, schema=CompetitorPicks, max_tokens=4000,
                on_retry=ctx.retry_hook("Mapper", "picking competitors"),
                prompt=(f"Portfolio companies: {dumps(about)}\nCandidates per portfolio company: {dumps(listing)}\n"
                        f"For each portfolio company, return up to {MAX_COMPETITORS_EACH} candidate ids that are "
                        "real competitors (or none)."))
            valid = {cid: {r["id"] for r, _ in sims} for cid, sims in candidates.items()}
            for item in res.items:
                if item.portfolio_id in valid:
                    chosen[item.portfolio_id] = [c for c in item.competitor_ids if c in valid[item.portfolio_id]]
        except LLMUnavailable:
            raise
        except LLMError:
            emit.recovered("Mapper", "Used the closest matches as competitors.", fallback="closest matches")
    for cid, sims in candidates.items():  # fallback: closest matches above a floor
        if cid not in chosen:
            chosen[cid] = [r["id"] for r, s in sims if s >= 0.2][:MAX_COMPETITORS_EACH]

    result = MapperResult(portfolio=[c for c, _ in picked], source="model" if sources == {"model"} else "dataset")
    for company, _ in picked:
        comps = [dataset.company(r) for r in (dataset.get(i) for i in chosen.get(company.id, [])[:MAX_COMPETITORS_EACH]) if r]
        result.competitors[company.id] = comps
        if comps:
            emit.finding("Mapper", f"{company.name} has {len(comps)} close "
                         f"{'rival' if len(comps) == 1 else 'rivals'}: {' and '.join(c.name for c in comps)}.",
                         company_id=company.id)
    return result


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

CANVAS_W, CANVAS_H = 800, 780
NODE_W, NODE_H = 160, 46
FUND_SIZE = 120


def _clamp(x: float, y: float) -> tuple[float, float]:
    return (round(max(0.0, min(CANVAS_W - NODE_W, x))), round(max(0.0, min(CANVAS_H - NODE_H, y))))


def _at(cx: float, cy: float, r: float, angle: float) -> tuple[float, float]:
    return cx + r * math.cos(angle) - NODE_W / 2, cy + r * math.sin(angle) - NODE_H / 2


def build_map(ctx: RunContext, reader: ReaderResult, mapper: MapperResult, deals: list[DealFlowItem],
              similar_to: Optional[dict[str, str]] = None) -> MapResponse:
    """Nodes and edges for the Market Map (fund in the middle, portfolio ring, competitors outside, picks)."""
    cx, cy = CANVAS_W / 2 - 22, CANVAS_H / 2 + 20
    fund_node_id = ctx.fund_id
    nodes = [GraphNode(id=fund_node_id, kind="fund", label=reader.fund_name, company_id=None,
                       logo=(data.get_fund(ctx.fund_id).logo or None), fit=None,
                       x=round(cx - FUND_SIZE / 2), y=round(cy - FUND_SIZE / 2))]
    edges: list[GraphEdge] = []
    used: set[str] = {fund_node_id}

    def edge(src: str, dst: str, kind: str) -> None:
        edges.append(GraphEdge(id=f"e{len(edges) + 1}", source=src, target=dst, kind=kind))  # type: ignore[arg-type]

    picks = [d for d in deals[:3]]
    pick_ids = {d.company.id for d in picks}  # a pick that is also a rival keeps its pick node
    n = len(mapper.portfolio)
    # Portfolio on the left half of the ring; the right half is kept for the picks.
    step = (math.pi * 1.0) / (n - 1) if n > 1 else 0.0
    angles = [math.pi * 0.6 + i * step for i in range(n)]
    for company, angle in zip(mapper.portfolio, angles):
        x, y = _clamp(*_at(cx, cy, 215, angle))
        nodes.append(GraphNode(id=company.id, kind="portfolio", label=company.name, company_id=company.id,
                               logo=company.logo, fit=None, x=x, y=y))
        used.add(company.id)
        edge(fund_node_id, company.id, "owns")
        comps = mapper.competitors.get(company.id, [])
        for j, comp in enumerate(comps):
            if comp.id in used or comp.id in pick_ids:
                edge(company.id, comp.id, "competes")
                continue
            spread = (j - (len(comps) - 1) / 2) * 0.32
            x2, y2 = _clamp(*_at(cx, cy, 345, angle + spread))
            nodes.append(GraphNode(id=comp.id, kind="competitor", label=comp.name, company_id=comp.id,
                                   logo=comp.logo, fit=None, x=x2, y=y2))
            used.add(comp.id)
            edge(company.id, comp.id, "competes")

    pick_angles = [-0.85, 0.0, 0.85]
    similar_to = similar_to or {}
    portfolio_ids = {c.id for c in mapper.portfolio}
    for d, a in zip(picks, pick_angles):
        cid = d.company.id
        x, y = _clamp(*_at(cx, cy, 300, a))
        nodes.append(GraphNode(id=cid, kind="pick", label=d.company.name, company_id=cid, logo=d.company.logo,
                               fit=d.fit, x=x, y=y))
        used.add(cid)
        edge(fund_node_id, cid, "candidate")
        like_id = similar_to.get(cid)
        if like_id in portfolio_ids:
            edge(cid, like_id, "similar")
        if d.conflict_with in portfolio_ids:
            edge(cid, d.conflict_with, "conflict")

    resp = MapResponse(fund_id=ctx.fund_id, nodes=nodes, edges=edges, shortlist=deals[:3],
                       picked_from=dataset.size() or 0, updated_label="updated just now",
                       mix_label=mix_label(deals))
    data.save_page(ctx.fund_id, "map", resp)
    n_comp = sum(1 for nd in nodes if nd.kind == "competitor")
    n_pick = sum(1 for nd in nodes if nd.kind == "pick")
    ctx.emit.done("Mapper", f"Market map ready: {len(mapper.portfolio)} portfolio companies, {n_comp} "
                  f"competitors and {n_pick} picks.", **plan("map", "done"))
    return resp


def _region(country: Optional[str]) -> str:
    if not country:
        return "other"
    if country == "UK":
        return "UK"
    if country == "US":
        return "US"
    if country in dataset.EUROPE:
        return "EU"
    return "other"


def mix_label(deals: list[DealFlowItem]) -> str:
    counts: dict[str, int] = {}
    for d in deals:
        r = _region(d.company.country)
        counts[r] = counts.get(r, 0) + 1
    order = ["UK", "EU", "US", "other"]
    parts = [f"{counts[k]} {k}" for k in order if counts.get(k)]
    return "Mix: " + " · ".join(parts) + " · no founder traits used" if parts else "No founder traits used"


__all__ = ["MapperResult", "find_competitors", "build_map", "mix_label"]
