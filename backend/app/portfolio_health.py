"""Portfolio health from real signals, never a default "Doing well".

exited    - the fund's site or the stage says sold / listed
at_risk   - news flagged a problem, or the website is down (no website found is a scraping gap: unknown)
watch     - news says a round is coming, or the last round was 12-30 months ago (the usual raise cycle)
good      - good news, or a round in the last 12 months
unknown   - no signal either way (said honestly)
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from .models import PortfolioColumn, PortfolioItem, PortfolioResponse, Signal

COLUMNS = [("at_risk", "Needs attention", "Something changed that a partner should look at"),
           ("watch", "Likely to raise soon", "Signals that a new round is coming: plan your follow-on"),
           ("good", "Doing well", "Growing, hiring or in the news for good reasons"),
           ("unknown", "Unknown", "No recent news or funding to judge by"),
           ("exited", "Exited", "Sold or listed")]
SHOWN_PER_COLUMN = 4
_EXIT_WORDS = ("acquired", "public", "ipo", "exited", "listed", "merged")


def _months_since(iso: str, today: date) -> Optional[int]:
    try:
        y, m = int(iso[:4]), int(iso[5:7]) if len(iso) >= 7 else 6
    except ValueError:
        return None
    return (today.year - y) * 12 + today.month - m


def classify(item: PortfolioItem, rec: Optional[dict], exited: bool = False,
             today: Optional[date] = None) -> tuple[str, list[Signal]]:
    """(health, signals) for one portfolio company. `rec` is its dataset row (company_detail.csv_record) or None."""
    today = today or date.today()
    c = item.company
    news = [s for s in item.signals if s.source_url or s.kind != "info"]
    stage = (c.stage or "").lower()
    if exited or item.health == "exited" or any(w in stage for w in _EXIT_WORDS):
        return "exited", news[:2]
    if news and item.health in ("at_risk", "watch", "good"):
        return item.health, news[:2]
    if news and any(s.kind == "risk" for s in news):
        return "at_risk", news[:2]
    site = (rec or {}).get("site_status", "")
    if site == "unreachable":
        return "at_risk", [Signal(kind="risk", label="Website is down", icon="triangle-alert")] + news[:1]
    no_site = site == "no_site" or (not c.website and not (rec or {}).get("website"))
    last = (rec or {}).get("last_funding_date") or (rec or {}).get("funding_date") or ""
    months = _months_since(last, today) if last else None
    if months is not None and 12 <= months <= 30:
        return "watch", [Signal(kind="timing", label=f"Last raised {last[:7]}", icon="timer")] + news[:1]
    if news:
        return "good", news[:2]
    if months is not None and 0 <= months < 12:
        return "good", [Signal(kind="strength", label=f"Raised {last[:7]}", icon="trending-up")]
    return "unknown", [Signal(kind="info", label="No website found" if no_site else "No recent news", icon="eye")]


def regroup(page: PortfolioResponse, exited_ids: frozenset[str] = frozenset()) -> PortfolioResponse:
    """Re-assign every company's health and rebuild the columns and KPIs."""
    from .company_detail import csv_record

    items: list[PortfolioItem] = []
    for col in page.columns:
        for it in col.items + col.rest:
            rec = csv_record(it.company.id, it.company.row_id)
            health, signals = classify(it, rec, exited=it.company.id in exited_ids)
            items.append(it.model_copy(update={"health": health, "signals": signals}))
    items.sort(key=lambda i: (not any(s.source_url for s in i.signals), i.company.name.lower()))
    page.columns = []
    for health, title, blurb in COLUMNS:
        col = [i for i in items if i.health == health]
        page.columns.append(PortfolioColumn(health=health, title=title, blurb=blurb, count=len(col),  # type: ignore[arg-type]
                                            items=col[:SHOWN_PER_COLUMN], rest=col[SHOWN_PER_COLUMN:],
                                            more=max(0, len(col) - SHOWN_PER_COLUMN)))
    page.kpis.likely_to_raise = sum(i.health == "watch" for i in items)
    page.kpis.need_attention = sum(i.health == "at_risk" for i in items)
    return page
