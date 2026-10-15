"""GET /api/map views: around the portfolio, by theme, new ground, competition, and "centre on" any company.

Built from what a run already stored (map/deals/portfolio pages + the `scores` memory) plus Modal
similar_companies for a centred map (timeout -> cache -> word-match fallback, never raises).
"""

from __future__ import annotations

import math
from collections import Counter
from functools import lru_cache
from typing import Optional

from . import data, modal_client, store
from .models import Company, DealFlowItem, GraphEdge, GraphNode, MapResponse, PortfolioResponse

VIEWS = ("portfolio", "theme", "new", "competition")
CX, CY = 400.0, 400.0  # centre of the design canvas (the frontend fits the view to the nodes' extent)
NODE_W, FUND = 160.0, 120.0
DOT = {"fund": FUND, "theme": 44.0, "portfolio": 30.0, "competitor": 22.0, "pick": 34.0}


def _node(id_: str, kind: str, label: str, x: float, y: float, c: Optional[Company] = None,
          fit: Optional[int] = None) -> GraphNode:
    """x, y = where the dot centre goes; stored as the node box's top-left."""
    w = FUND if kind == "fund" else NODE_W
    return GraphNode(id=id_, kind=kind, label=label, company_id=c.id if c else None,
                     logo=c.logo if c else None, fit=fit, x=round(x - w / 2, 1), y=round(y - DOT[kind] / 2, 1))


def _ring(n: int, r: float, cx: float = CX, cy: float = CY, start: float = -math.pi / 2, spread: float = 2 * math.pi):
    for i in range(n):
        a = start + spread * (i + 0.5) / max(n, 1) if spread < 2 * math.pi else start + spread * i / max(n, 1)
        yield cx + r * math.cos(a), cy + r * math.sin(a)


@lru_cache(maxsize=20000)
def _words(text: str) -> frozenset:
    return frozenset(modal_client._tokens(text))


def _close(a: Company, b: Company) -> float:
    """0..1, how alike two companies read (words + sector). Cheap, local, no model."""
    wa = _words(f"{a.name} {a.one_liner}")
    wb = _words(f"{b.name} {b.one_liner}")
    words = len(wa & wb) / max(1, min(len(wa), len(wb))) if wa and wb else 0.0
    return min(1.0, words + (0.35 if a.sector and a.sector == b.sector else 0.0))


def _label(score: float, same_sector: bool) -> str:
    if score >= 0.6:
        return "very similar"
    return "same customers" if same_sector else "similar"


def _portfolio(fund_id: str) -> list[Company]:
    try:
        page: PortfolioResponse = data.portfolio(fund_id)
        return [p.company for col in page.columns for p in col.items]
    except data.NoData:
        return []


def _pool(fund_id: str, base: MapResponse) -> list[DealFlowItem]:
    """Every scored startup we know for this fund, best fit first: deals page, map shortlist, stored scores."""
    items: dict[str, DealFlowItem] = {}
    try:
        for i in data.deals(fund_id).items:
            items.setdefault(i.company.id, i)
    except data.NoData:
        pass
    for i in base.shortlist:
        items.setdefault(i.company.id, i)
    scores = store.get_memory(fund_id, "scores") or {}
    if scores and data.csv_available():
        known_rows = {i.company.row_id for i in items.values()}
        for r in data._csv_rows():
            fit = scores.get(str(r["row_id"]))
            if fit is None or r["row_id"] in known_rows:
                continue
            c = Company(**{k: v for k, v in r.items() if not k.startswith("_")})
            items[c.id] = DealFlowItem(rank=0, company=c, fit=int(fit), seen_label="", status="new")
    out = sorted(items.values(), key=lambda i: -i.fit)
    for n, i in enumerate(out, 1):
        i.rank = n
    return out


def _fit_lookup(fund_id: str, pool: list[DealFlowItem]) -> tuple[dict[str, int], dict[int, int]]:
    by_id = {i.company.id: i.fit for i in pool}
    by_row = {int(k): int(v) for k, v in (store.get_memory(fund_id, "scores") or {}).items() if str(k).isdigit()}
    return by_id, by_row


def _ok(c: Company, sector: Optional[str], country: Optional[str], stage: Optional[str]) -> bool:
    return ((not sector or (c.sector or "").lower() == sector.lower())
            and (not country or (c.country or "").lower() == country.lower())
            and (not stage or (c.stage or "").lower() == stage.lower()))


def _resp(base: MapResponse, nodes, edges, shortlist, view: str, note: str, pool, center_id=None) -> MapResponse:
    opts = {"sectors": set(), "countries": set(), "stages": set()}
    for i in pool:
        if i.company.sector:
            opts["sectors"].add(i.company.sector)
        if i.company.country:
            opts["countries"].add(i.company.country)
        if i.company.stage:
            opts["stages"].add(i.company.stage)
    return base.model_copy(update={
        "nodes": nodes, "edges": edges,
        "shortlist": [i.model_copy(update={"rank": k}) for k, i in enumerate(shortlist[:10], 1)] or base.shortlist, "view": view,
        "center_id": center_id, "note": note,
        "sectors": sorted(opts["sectors"]), "countries": sorted(opts["countries"]), "stages": sorted(opts["stages"]),
    })


async def build(fund_id: str, view: str = "portfolio", center: Optional[str] = None, sector: Optional[str] = None,
                country: Optional[str] = None, stage: Optional[str] = None, limit: int = 10) -> MapResponse:
    base = data.market_map(fund_id)  # raises NoData -> 404, as before
    limit = max(1, min(int(limit or 10), 50))
    view = view if view in VIEWS else "portfolio"
    pool = _pool(fund_id, base)
    port = _portfolio(fund_id)
    port_ids = {c.id for c in port}
    picks = [i for i in pool if i.company.id not in port_ids and _ok(i.company, sector, country, stage)]
    fund_name = next((n.label for n in base.nodes if n.kind == "fund"), "The fund")

    if center:
        return await _centred(fund_id, base, pool, port_ids, center, sector, country, stage, limit)
    if view == "theme":
        return _themes(base, pool, port, picks[:limit], fund_name)
    if view == "new":
        return _new_ground(base, pool, port, picks, limit, fund_name)
    if view == "competition":
        return _competition(base, pool)
    return _around(base, pool, port, picks[:limit], sector or country or stage or limit != 10)


def _around(base: MapResponse, pool, port: list[Company], picks: list[DealFlowItem], changed: bool) -> MapResponse:
    note = "Our next picks, each linked to the company we own that it is most like"
    if not changed:  # the map the Mapper drew, untouched
        return _resp(base, base.nodes, _labelled(base).edges, base.shortlist, "portfolio", note, pool)
    keep = [n for n in base.nodes if n.kind != "pick"]
    by_company = {n.company_id: n for n in keep if n.kind == "portfolio"}
    edges = [e for e in _labelled(base).edges if all(_find(keep, x) for x in (e.source, e.target))]
    fund = next(n for n in keep if n.kind == "fund")
    rings = [330.0, 410.0]
    nodes = list(keep)
    for k, (item, (x, y)) in enumerate(zip(picks, _staggered(len(picks), rings))):
        nid = f"pick-{item.company.id}"
        nodes.append(_node(nid, "pick", item.company.name, x, y, item.company, item.fit))
        best = max(port, key=lambda p: _close(item.company, p), default=None)
        target = by_company.get(best.id) if best else None
        if target is not None and _close(item.company, best) > 0.2:
            s = _close(item.company, best)
            edges.append(GraphEdge(id=f"e-{nid}", source=nid, target=target.id, kind="similar",
                                   label=_label(s, item.company.sector == best.sector)))
        else:
            edges.append(GraphEdge(id=f"e-{nid}", source=fund.id, target=nid, kind="candidate"))
    return _resp(base, nodes, edges, picks, "portfolio", note, pool)


def _staggered(n: int, rings: list[float]):
    for i, (x, y) in enumerate(_ring(n, 1.0, 0, 0)):
        r = rings[i % len(rings)] + 18 * (n > 24) * (i % 3)
        yield CX + r * x, CY + r * y


def _find(nodes, nid):
    return next((n for n in nodes if n.id == nid), None)


def _labelled(base: MapResponse) -> MapResponse:
    words = {"competes": "rival", "conflict": "rival of a company we own", "similar": "very similar"}
    return base.model_copy(update={"edges": [e.model_copy(update={"label": e.label or words.get(e.kind)})
                                             for e in base.edges]})


def _themes(base, pool, port: list[Company], picks: list[DealFlowItem], fund_name: str) -> MapResponse:
    counts = Counter([c.sector or "Other" for c in port] + [i.company.sector or "Other" for i in picks])
    themes = [t for t, _ in counts.most_common(7)]
    theme_of = lambda s: s if s in themes else "Other"  # noqa: E731
    if "Other" not in themes and any(theme_of(c.sector) == "Other" for c in port):
        themes.append("Other")
    fund = _node("fund", "fund", fund_name, CX, CY)
    nodes, edges = [fund], []
    for t, (hx, hy) in zip(themes, _ring(len(themes), 420)):
        hid = f"theme-{data.slugify(t) or 'other'}"
        nodes.append(_node(hid, "theme", t, hx, hy))
        edges.append(GraphEdge(id=f"e-{hid}", source="fund", target=hid, kind="owns"))
        members = [("portfolio", c, None) for c in port if theme_of(c.sector) == t][:6]
        members += [("pick", i.company, i.fit) for i in picks if theme_of(i.company.sector) == t]
        out = math.atan2(hy - CY, hx - CX)
        n = len(members)
        r = 110 if n <= 4 else 70 + 22 * n  # big clusters wrap all the way round their hub
        arc = (out - 1.4, 2.8) if n <= 4 else (out + math.pi, 2 * math.pi)
        for (kind, c, fit), (x, y) in zip(members, _ring(n, r, hx, hy, *arc)):
            nid = f"{kind}-{c.id}"
            nodes.append(_node(nid, kind, c.name, x, y, c, fit))
            edges.append(GraphEdge(id=f"e-{nid}", source=hid, target=nid, kind="owns" if kind == "portfolio" else "candidate"))
    note = "Everything grouped by what it does. Picks don't need to sit next to a company we own"
    return _resp(base, nodes, edges, picks, "theme", note, pool)


def _new_ground(base, pool, port: list[Company], picks: list[DealFlowItem], limit: int, fund_name: str) -> MapResponse:
    def closeness(i: DealFlowItem) -> float:
        like = next((p.value for p in i.fit_parts if p.label == "Like the portfolio"), 0.0)
        return max(like * 0.8, max((_close(i.company, p) for p in port), default=0.0))

    scored = sorted(((i, closeness(i)) for i in picks[:200]), key=lambda t: (t[1] >= 0.5, -t[0].fit * (1.2 - t[1])))
    chosen = scored[:limit]
    fund = _node("fund", "fund", fund_name, CX, CY)
    nodes, edges = [fund], []
    for c, (x, y) in zip(port[:12], _ring(min(len(port), 12), 150)):
        nodes.append(_node(f"portfolio-{c.id}", "portfolio", c.name, x, y, c))
        edges.append(GraphEdge(id=f"e-p-{c.id}", source="fund", target=f"portfolio-{c.id}", kind="owns"))
    for (item, _), (x, y) in zip(chosen, _staggered(len(chosen), [340.0, 420.0])):
        nid = f"pick-{item.company.id}"
        nodes.append(_node(nid, "pick", item.company.name, x, y, item.company, item.fit))
        edges.append(GraphEdge(id=f"e-{nid}", source="fund", target=nid, kind="candidate"))
    note = "Strong fits that look like nothing we own yet: room for a new bet"
    return _resp(base, nodes, edges, [i for i, _ in chosen], "new", note, pool)


def _competition(base: MapResponse, pool) -> MapResponse:
    lab = _labelled(base)
    conflict_picks = {e.source for e in lab.edges if e.kind == "conflict"} | {e.target for e in lab.edges if e.kind == "conflict"}
    nodes = [n for n in lab.nodes if n.kind != "pick" or n.id in conflict_picks]
    ids = {n.id for n in nodes}
    edges = [e for e in lab.edges if e.source in ids and e.target in ids]
    note = "The companies we own and who they compete with"
    short = [i for i in base.shortlist if f"pick-{i.company.id}" in ids or i.conflict_with]
    return _resp(base, nodes, edges, short, "competition", note, pool)


async def _centred(fund_id, base, pool, port_ids, center, sector, country, stage, limit) -> MapResponse:
    by_id, by_row = _fit_lookup(fund_id, pool)
    known = data._known_companies(fund_id)
    hub = known.get(center) or data.company(center, fund_id)
    r = await modal_client.similar_companies(hub.id if hub else center, k=min(60, limit * 3), timeout=8)
    value = r.value if isinstance(r.value, dict) else {}
    if hub is None and value.get("query_company"):
        q = value["query_company"]
        hub = Company(id=q["id"], row_id=q.get("row_id"), name=q["name"], one_liner=q.get("one_liner") or "",
                      sector=q.get("sector") or "", stage=q.get("stage") or "", country=q.get("country"))
    if hub is None:
        raise data.NoData("We couldn't find that company.")
    cid = {n.id: n.company_id for n in base.nodes}
    rivals = {frozenset((cid.get(e.source), cid.get(e.target))) for e in base.edges if e.kind in ("competes", "conflict")}
    near = []
    for x in value.get("results", []):
        if not isinstance(x, dict) or x.get("id") == hub.id:
            continue
        c = known.get(str(x.get("id"))) or Company(
            id=str(x.get("id")), row_id=x.get("row_id"), name=x.get("name") or "?", one_liner=x.get("one_liner") or "",
            sector=x.get("sector") or "", stage=x.get("stage") or "", country=x.get("country"),
            website=x.get("website"), founded=x.get("founded"))
        if _ok(c, sector, country, stage):
            near.append((c, float(x.get("score") or 0)))
        if len(near) >= limit:
            break
    hub_fit = by_id.get(hub.id) or by_row.get(hub.row_id or -1)
    nodes = [_node(f"center-{hub.id}", "fund", hub.name, CX, CY, hub, hub_fit)]
    edges = []
    top = max((s for _, s in near), default=1.0) or 1.0
    shortlist = []
    for k, ((c, s), (x, y)) in enumerate(zip(near, _staggered(len(near), [260.0, 340.0]))):
        fit = by_id.get(c.id) or by_row.get(c.row_id or -1)
        kind = "portfolio" if c.id in port_ids else ("pick" if fit is not None else "competitor")
        nid = f"{kind}-{c.id}"
        nodes.append(_node(nid, kind, c.name, x, y, c, fit))
        rival = frozenset((hub.id, c.id)) in rivals
        label = "rival" if rival else _label(s / top if top > 1 else s, c.sector == hub.sector)
        edges.append(GraphEdge(id=f"e-{nid}", source=nodes[0].id, target=nid,
                               kind="competes" if rival else ("similar" if kind == "pick" else "owns"), label=label))
        if kind == "pick":
            shortlist.append(next((i for i in pool if i.company.id == c.id), None)
                             or DealFlowItem(rank=k + 1, company=c, fit=fit or 0, seen_label="", status="new"))
    src = "the model" if r.source == "modal" else ("the model (saved answer)" if r.source == "cache" else "a word match (model offline)")
    note = f"The {len(near)} companies most like {hub.name}, found by {src}, with their fit for this fund"
    return _resp(base, nodes, edges, shortlist, "center", note, pool, center_id=hub.id)
