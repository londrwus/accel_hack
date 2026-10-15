"""Watch mode: what changed since the last run ("the always-on analyst").

At the end of every live run we save a small snapshot of the results (`memory: watch:snapshot`). The next
run (scheduled by app.runs.watch_loop, or "Simulate next morning") diffs against it and reports changes in
the feed as `finding` events with tag "Changed" (or "New match" for new picks) and data.change set, plus the
gold "Since yesterday" note (RunState.since_last_run).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .. import store
from ..models import DealFlowItem
from .market import MarketResult

SNAPSHOT_KEY = "watch:snapshot"
FIT_CHANGE = 5  # points
MAX_EVENTS = 6


def snapshot(deals: list[DealFlowItem], health: dict[str, dict], market: Optional[MarketResult],
             competitors: list[str], run_id: str) -> dict:
    """health: {company_id: {"name", "health"}} for every portfolio company."""
    return {
        "run_id": run_id,
        "at": store.now_iso(),
        "deals": {d.company.id: {"name": d.company.name, "fit": d.fit} for d in deals},
        "health": health,
        "competitors": sorted(set(competitors)),
        "raises": sorted({r.company for r in (market.other_raises if market else [])}),
    }


def diff(prev: dict, cur: dict) -> list[dict]:
    """Plain-English changes, most important first."""
    changes: list[dict] = []
    for cid, d in cur["deals"].items():
        if cid not in prev.get("deals", {}):
            changes.append({"change": "new_match", "company_id": cid, "fit": d["fit"],
                            "message": f"New since last time: {d['name']} (fit {d['fit']}%)."})
    for cid, d in prev.get("deals", {}).items():
        if cid not in cur["deals"]:
            changes.append({"change": "dropped", "company_id": cid,
                            "message": f"{d['name']} dropped out of the top picks."})
        else:
            delta = cur["deals"][cid]["fit"] - d["fit"]
            if abs(delta) >= FIT_CHANGE:
                word = "up" if delta > 0 else "down"
                changes.append({"change": "fit", "company_id": cid, "fit": cur["deals"][cid]["fit"],
                                "message": f"{d['name']}'s fit went {word} from {d['fit']}% to "
                                           f"{cur['deals'][cid]['fit']}%."})
    labels = {"at_risk": "needs attention", "watch": "looks likely to raise soon", "good": "is doing well",
              "exited": "has exited"}
    for cid, h in cur["health"].items():
        before = prev.get("health", {}).get(cid)
        if before and before["health"] != h["health"]:
            changes.append({"change": "health", "company_id": cid,
                            "message": f"{h['name']} now {labels.get(h['health'], h['health'])}."})
    new_raises = [r for r in cur["raises"] if r not in set(prev.get("raises", []))]
    for r in new_raises[:3]:
        changes.append({"change": "competitor_raised", "message": f"{r} raised money since last time."})
    new_comps = [c for c in cur["competitors"] if c not in set(prev.get("competitors", []))]
    if new_comps:
        changes.append({"change": "new_competitors", "count": len(new_comps),
                        "message": f"Spotted {len(new_comps)} new {'competitor' if len(new_comps) == 1 else 'competitors'} "
                                   "around the portfolio."})
    order = {"new_match": 0, "health": 1, "competitor_raised": 2, "fit": 3, "new_competitors": 4, "dropped": 5}
    changes.sort(key=lambda c: order.get(c["change"], 9))
    return changes


def since_label(prev_at: str) -> str:
    try:
        then = datetime.fromisoformat(prev_at.replace("Z", "+00:00"))
    except ValueError:
        return "Since last run"
    hours = (datetime.now(timezone.utc) - then).total_seconds() / 3600
    if 12 <= hours < 36:
        return "Since yesterday"
    if hours < 12:
        return "Since the last run"
    return f"Since {then.strftime('%a')} {then.day} {then.strftime('%b')}"


def summary(changes: list[dict], prev_at: str) -> Optional[str]:
    if not changes:
        return None
    n_new = sum(c["change"] == "new_match" for c in changes)
    n_raise = sum(c["change"] == "competitor_raised" for c in changes)
    n_health = sum(c["change"] == "health" for c in changes)
    parts = []
    if n_new:
        parts.append(f"{n_new} new {'match' if n_new == 1 else 'matches'}")
    if n_raise:
        parts.append(f"{n_raise} {'competitor' if n_raise == 1 else 'competitors'} raised")
    if n_health:
        parts.append(f"{n_health} portfolio {'change' if n_health == 1 else 'changes'}")
    if not parts:
        parts.append(f"{len(changes)} {'change' if len(changes) == 1 else 'changes'}")
    return f"{since_label(prev_at)}: {', '.join(parts)}"


def report(ctx: Any, cur: dict) -> Optional[str]:
    """Diff against the last snapshot, emit the changes, save the new snapshot. Returns the summary line."""
    prev = store.get_memory(ctx.fund_id, SNAPSHOT_KEY)
    store.set_memory(ctx.fund_id, SNAPSHOT_KEY, cur)
    if not prev:
        return None
    changes = diff(prev, cur)
    if not changes:
        ctx.emit.step("Partner", "Compared with the last run: nothing important changed.")
        return None
    for c in changes[:MAX_EVENTS]:
        tag = "New match" if c["change"] == "new_match" else "Changed"
        data = {k: v for k, v in c.items() if k != "message"}
        ctx.emit.finding("Partner", c["message"], tag=tag, **data)
    return summary(changes, prev.get("at", ""))
