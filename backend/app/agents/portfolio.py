"""Builds the Portfolio page from Reader's list and Market's news (no extra model calls)."""

from __future__ import annotations

from ..models import PortfolioColumn, PortfolioItem, PortfolioKpis, PortfolioResponse, Signal
from .finder import icon_for
from .market import MarketResult
from .reader import ReaderResult

COLUMNS = [("at_risk", "Needs attention", "Something changed that a partner should look at"),
           ("watch", "Likely to raise soon", "Signals that a new round is coming: plan your follow-on"),
           ("good", "Doing well", "Growing, hiring or in the news for good reasons"),
           ("exited", "Exited", "Sold or listed")]
SHOWN_PER_COLUMN = 4


def build(fund_id: str, reader: ReaderResult, market: MarketResult) -> tuple[PortfolioResponse, dict[str, dict]]:
    """The Portfolio page, plus {company_id: {"name", "health"}} for every company (for watch-mode diffs)."""
    news: dict[str, list] = {}
    for n in market.portfolio_news:
        news.setdefault(n.company.strip().lower(), []).append(n)
    items: list[PortfolioItem] = []
    for p in reader.portfolio:
        found = news.get(p.company.name.lower(), [])
        if p.exited:
            health = "exited"
        elif found:
            rank = {"at_risk": 0, "watch": 1, "exited": 2, "good": 3}
            health = min((n.health for n in found), key=lambda h: rank[h])
        else:
            health = "good"
        signals = [Signal(kind=n.kind, label=n.label[:40], icon=icon_for(n.kind, n.label), source_url=n.url)
                   for n in found[:2]]
        if not signals and health == "good" and market.searched:
            signals = [Signal(kind="info", label="No news this quarter", icon="eye", source_url=None)]
        items.append(PortfolioItem(company=p.company, health=health, signals=signals,  # type: ignore[arg-type]
                                   updated_label=None if health == "exited" else
                                   ("Updated today" if found else None)))
    # Companies with news first inside each column.
    items.sort(key=lambda i: (not any(s.source_url for s in i.signals), i.company.name.lower()))
    columns = []
    for health, title, blurb in COLUMNS:
        col = [i for i in items if i.health == health]
        columns.append(PortfolioColumn(health=health, title=title, blurb=blurb, count=len(col),  # type: ignore[arg-type]
                                       items=col[:SHOWN_PER_COLUMN], rest=col[SHOWN_PER_COLUMN:],
                                       more=max(0, len(col) - SHOWN_PER_COLUMN)))
    kpis = PortfolioKpis(companies_backed=len(items), invested="Not public",
                         likely_to_raise=sum(i.health == "watch" for i in items),
                         need_attention=sum(i.health == "at_risk" for i in items),
                         new_signals_this_week=len(market.portfolio_news))
    health = {i.company.id: {"name": i.company.name, "health": i.health} for i in items}
    return PortfolioResponse(fund_id=fund_id, kpis=kpis, columns=columns), health
