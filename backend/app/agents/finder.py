"""Deal Finder: scores every startup in the dataset against the fund, then picks and explains the best 10.

1. `score`: Modal score_fit (fallback: the local dataset scorer) -> top 150 + a fit for every row (Universe page).
   Then Jev (a second, independent judge) rates each of the top 150 against the thesis; the fit becomes
   60% model + 40% judge, the judge's view shows as the fit part "Fits the thesis (judge)", and the list is
   re-sorted. The best 50 go on. Without Jev, the model's order is kept.
2. `rank`: the worker model reads the top 50 closely, picks 10, writes the "why" bullets and signal chips,
   and flags clashes with the portfolio. Fallback: the top 10 by score with plain template reasons.
   Shown deals with no stage or sector in the dataset get a Jev best guess, marked "(estimated)".
Human feedback (Approve/Pass on earlier picks) nudges sector weights before scoring.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .. import config, data, store
from ..models import DealCounts, DealFlowItem, DealsResponse, FitPart, FundDNA, Signal
from ..tools import dataset, jev
from . import ml
from .context import RunContext, plan
from .llm import WORKER_MODEL, LLMError, LLMUnavailable, dumps
from .mapper import MapperResult, mix_label
from .reader import ReaderResult, dataset_rows

SHORTLIST = 10
# How many candidates get each treatment comes from the run profile (config.PROFILES, RUN_PROFILE=fast|thorough):
#   consider     read closely by the worker model (fast 20, thorough 50)
#   rerank_pool  judged by Jev against the thesis (fast 60, thorough 150)
CONSIDER = 50  # thorough-profile values, kept for reference
RERANK_POOL = 150
MAX_PER_LOOKALIKE = 3  # at most this many picks may look like the same portfolio company
MODEL_WEIGHT, JUDGE_WEIGHT = 0.6, 0.4
JUDGE_PART = "Fits the thesis (judge)"
ESTIMATED = " (estimated)"
MAX_DEALS_PAGE = 60


class PickSignal(BaseModel):
    kind: Literal["timing", "strength", "info", "risk"]
    label: str


class Pick(BaseModel):
    company_id: str
    fit: int
    why: list[str]
    signals: list[PickSignal]
    similar_to: Optional[str] = None  # portfolio company id it looks like
    conflict_with: Optional[str] = None  # portfolio company id it competes with


class Shortlist(BaseModel):
    picks: list[Pick]


class ScoreResult(BaseModel):
    """Top candidates from scoring (row ids only, so it can be checkpointed)."""

    top: list[dict] = Field(default_factory=list)  # [{"company_id", "fit", "parts", "like"}]
    scored: int = 0
    seconds: float = 0.0
    source: str = "dataset"


class FinderResult(BaseModel):
    deals: list[DealFlowItem]
    similar_to: dict[str, str] = Field(default_factory=dict)  # pick id -> portfolio id
    new_ids: list[str] = Field(default_factory=list)


SYSTEM = (
    "You are Deal Finder, part of Bellwether, a research assistant for a venture capital fund. You pick the "
    "startups that best fit the fund's past behaviour and explain each pick in plain English a non-expert "
    "understands. Judge only the company: what it does, its market, stage, location and traction. Never use "
    "or infer founders' gender, age, ethnicity, nationality or looks. A fit score means 'fits this fund's past "
    "behaviour', not 'will succeed'. Flag a clash when a startup competes with a company the fund already owns."
)

_ICONS = [(("raising", "round", "raised", "funding"), "trending-up"), (("like ", "similar"), "link"),
          (("hiring", "team", "engineer"), "users"), (("revenue", "growth", "grew", "users up", "customers"), "chart-line"),
          (("compet", "clash", "risk"), "triangle-alert"), (("news", "press", "sifted", "techcrunch"), "newspaper"),
          (("award", "prize", "winner"), "award"), (("grant", "government", "nhs", "council"), "landmark"),
          (("partner", "deal with", "signed"), "handshake"), (("stealth", "early", "pre-seed"), "timer")]
_DEFAULT_ICON = {"timing": "trending-up", "strength": "chart-line", "info": "newspaper", "risk": "triangle-alert"}


def icon_for(kind: str, label: str) -> str:
    low = label.lower()
    for words, icon in _ICONS:
        if any(w in low for w in words):
            return icon
    return _DEFAULT_ICON.get(kind, "eye")


def seen_label(first_seen: str | None) -> str:
    if not first_seen:
        return "now"
    try:
        then = datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
    except ValueError:
        return "now"
    mins = (datetime.now(timezone.utc) - then).total_seconds() / 60
    if mins < 60:
        return f"{max(1, int(mins))}m"
    if mins < 60 * 24:
        return f"{int(mins // 60)}h"
    if mins < 60 * 24 * 7:
        return f"{int(mins // (60 * 24))}d"
    return f"{int(mins // (60 * 24 * 7))}w"


# ---------------------------------------------------------------------------
# 1. Score
# ---------------------------------------------------------------------------


async def score(ctx: RunContext, reader: ReaderResult, dna: FundDNA) -> ScoreResult:
    emit = ctx.emit
    n = dataset.size()
    weights = store.get_memory(ctx.fund_id, "thesis_weights", {}) or {}
    if weights:
        liked = [k.split(":", 1)[1] for k, v in weights.items() if v > 0][:2]
        passed = [k.split(":", 1)[1] for k, v in weights.items() if v < 0][:2]
        bits = ([f"a little more weight on {', '.join(liked)}"] if liked else []) + \
               ([f"a little less on {', '.join(passed)}"] if passed else [])
        if bits:
            emit.step("Deal Finder", f"Using your earlier decisions: {' and '.join(bits)}.")
    emit.tool("Deal Finder", "score_fit", f"Scoring {n:,} startups against the fund's thesis.",
              **plan("deals", "working"))
    t0 = time.perf_counter()
    owned = [p.company.id for p in reader.portfolio]
    pool_n, consider = config.cap("rerank_pool"), config.cap("consider")
    top, all_scores, source = await ml.score(dna.model_dump(mode="json"), dataset_rows(reader), pool_n,
                                             sector_weights=weights, exclude=owned)
    secs = round(time.perf_counter() - t0, 1)
    if source == "dataset" and n:
        emit.recovered("Deal Finder", "The scoring model on Modal didn't answer in time, so I scored with the "
                       "simpler local model.", fallback="local scorer")
    emit.finding("Deal Finder", f"Scored all {n:,} startups in {secs} seconds. "
                 f"{min(len(top), consider)} look promising.", scored=n, seconds=secs)
    top = await rerank(ctx, reader, dna, top, all_scores)
    data.save_scores(ctx.fund_id, all_scores)
    return ScoreResult(top=[{"company_id": c["row"]["id"], "fit": c["fit"], "parts": c["parts"],
                             "like": c["like"]["id"] if c.get("like") else None,
                             "model_fit": c.get("model_fit", c["fit"]), "judge": c.get("judge")}
                            for c in top[:consider]],
                       scored=n, seconds=secs, source=source)


def thesis_state(fund_name: str, dna: FundDNA) -> dict:
    """What the judge sees about the fund (no people, no scores)."""
    return {"name": fund_name, "summary": dna.summary, "stage": dna.stage, "geography": dna.geo,
            "cheque": dna.cheque, "sectors": [s.name for s in dna.sectors[:8]], "themes": dna.themes[:8]}


async def rerank(ctx: RunContext, reader: ReaderResult, dna: FundDNA, top: list[dict],
                 all_scores: dict[int, int]) -> list[dict]:
    """Blend the model's fit with Jev's thesis-fit judgment for the top candidates and re-sort them.

    Each candidate is judged on its own (one small Jev call each, run in parallel). Candidates the judge
    couldn't rate keep their model fit. Updates `all_scores` so the Universe page shows the same numbers.
    """
    emit = ctx.emit
    pool_n = config.cap("rerank_pool")
    pool = top[:pool_n]
    if not pool or not jev.enabled():
        return top
    emit.step("Deal Finder", f"Asking a second judge (Jev) to read each of the top {len(pool)} against "
              f"{reader.fund_name}'s thesis.", judge="Jev", candidates=len(pool))
    before = [c["row"]["id"] for c in pool[:SHORTLIST]]
    try:
        fits = await jev.thesis_fit(thesis_state(reader.fund_name, dna), [dataset.brief(c["row"]) for c in pool],
                                    deadline_s=config.cap("rerank_deadline_s"))
    except Exception:  # an optional judge must never stop the run
        fits = {}
    if not fits:
        emit.recovered("Deal Finder", "The second judge didn't answer, so the ranking uses the scoring model "
                       "alone.", fallback="model scores")
        return top
    for c in pool:
        j = fits.get(c["row"]["id"])
        if j is None:
            continue
        c["model_fit"] = c["fit"]
        c["judge"] = round(j, 3)
        c["fit"] = max(0, min(99, round(MODEL_WEIGHT * c["fit"] + JUDGE_WEIGHT * 100 * j)))
        c["parts"] = {**c["parts"], JUDGE_PART: round(j, 2)}
        all_scores[c["row"]["row_id"]] = c["fit"]
    pool.sort(key=lambda c: -c["fit"])
    after = [c["row"]["id"] for c in pool[:SHORTLIST]]
    moved_in = [cid for cid in after if cid not in before]
    names = [c["row"]["name"] for c in pool if c["row"]["id"] in moved_in][:2]
    judged = (f"the top {len(pool)}" if len(fits) >= len(pool) else f"{len(fits)} of the top {len(pool)}")
    msg = f"Re-ranked {judged} with the judge's view of the thesis (60% scoring model, 40% judge). "
    if moved_in:
        msg += (f"{len(moved_in)} {'company' if len(moved_in) == 1 else 'companies'} moved into the top "
                f"{SHORTLIST}, including {' and '.join(names)}.")
    else:
        msg += f"The top {SHORTLIST} stayed the same, so both agree."
    emit.finding("Deal Finder", msg, judge="Jev", reranked=len(pool), judged=len(fits),
                 moved_into_top=len(moved_in), weights={"model": MODEL_WEIGHT, "judge": JUDGE_WEIGHT})
    return pool + top[pool_n:]


async def guess_missing(company_ids: list[str], deadline_s: float = 30.0) -> dict[str, "jev.Estimate"]:
    """Jev's best guess for a missing stage / sector, for these companies ({company_id: Estimate})."""
    if not jev.enabled():
        return {}
    todo = []
    for cid in dict.fromkeys(company_ids):
        r = dataset.get(cid)
        if r and (not r["stage_label"] or not r["sector_label"]):
            todo.append(r)
    if not todo:
        return {}
    sectors = dataset.sector_labels()
    try:
        guesses = await jev.gather_limited(
            [jev.estimate_fields(dataset.brief(r), need_stage=not r["stage_label"],
                                 need_sector=not r["sector_label"], sectors=sectors) for r in todo],
            deadline_s=deadline_s)
    except Exception:
        return {}
    return {r["id"]: g for r, g in zip(todo, guesses) if g is not None}


async def fill_estimates(ctx: RunContext, items: list[DealFlowItem],
                         guesses: Optional["asyncio.Future"] = None) -> None:
    """Best guess for a missing stage / sector on the shown deals, marked "(estimated)".

    `guesses`: a guess_missing() task started earlier (e.g. alongside the close read), so nothing waits here."""
    if not jev.enabled():
        return
    try:
        found = await guesses if guesses is not None else await guess_missing([i.company.id for i in items])
    except Exception:
        return
    stages = sectors_n = 0
    for item in items:
        g = found.get(item.company.id)
        if g is None:
            continue
        if g.stage:
            item.company.stage = g.stage + ESTIMATED
            stages += 1
        if g.sector:
            item.company.sector = g.sector + ESTIMATED
            sectors_n += 1
    if stages or sectors_n:
        bits = ([f"the stage of {stages} {'company' if stages == 1 else 'companies'}"] if stages else []) + \
               ([f"the sector of {sectors_n}"] if sectors_n else [])
        ctx.emit.step("Deal Finder", f"The dataset was missing {' and '.join(bits)}, so I filled in a best guess "
                      "from the description. Each one is marked as estimated.", judge="Jev",
                      estimated_stage=stages, estimated_sector=sectors_n)


# ---------------------------------------------------------------------------
# 2. Rank, explain, check for clashes
# ---------------------------------------------------------------------------


def _fallback_picks(scored: ScoreResult, names: dict[str, str]) -> list[Pick]:
    picks = []
    for c in scored.top[:SHORTLIST]:
        r = dataset.get(c["company_id"])
        if not r:
            continue
        parts = c["parts"]
        why = []
        if c.get("like") and c["like"] in names:
            why.append(f"Works on something close to {names[c['like']]}, which the fund owns")
        if parts.get("Right location", 0) >= 0.8:
            why.append(f"Based in {r['country_label']}, where the fund invests")
        if parts.get("Right stage", 0) >= 0.8:
            why.append(f"At the {r['stage_label'] or 'early'} stage the fund usually backs")
        why = why or [f"{r['sector_label'] or 'Its sector'} matches what the fund backs"]
        picks.append(Pick(company_id=r["id"], fit=c["fit"], why=why,
                          signals=[PickSignal(kind="strength", label=f"Like {names[c['like']]}")]
                          if c.get("like") in names else [], similar_to=c.get("like")))
    return picks


def _best_picks(picks: list[Pick], by_id: dict[str, dict]) -> list[Pick]:
    """The best SHORTLIST picks by blended fit, one per company, at most MAX_PER_LOOKALIKE per look-alike."""
    seen: set[str] = set()
    per_like: dict[str, int] = {}
    out: list[Pick] = []
    for p in sorted(picks, key=lambda p: -(0.6 * by_id[p.company_id]["fit"] + 0.4 * max(0, min(100, p.fit)))):
        if p.company_id in seen:
            continue
        like = p.similar_to or by_id[p.company_id].get("like") or ""
        if like and per_like.get(like, 0) >= MAX_PER_LOOKALIKE:
            continue
        seen.add(p.company_id)
        if like:
            per_like[like] = per_like.get(like, 0) + 1
        out.append(p)
        if len(out) >= SHORTLIST:
            break
    if len(out) < SHORTLIST:  # the look-alike cap left gaps: fill them with the next best
        for p in sorted(picks, key=lambda p: -(0.6 * by_id[p.company_id]["fit"] + 0.4 * max(0, min(100, p.fit)))):
            if p.company_id not in seen and len(out) < SHORTLIST:
                seen.add(p.company_id)
                out.append(p)
    return out


async def _close_read(ctx: RunContext, reader: ReaderResult, dna: FundDNA, names: dict[str, str],
                      rivals: dict[str, list[str]], cands: list[dict], partial: bool) -> list[Pick]:
    """One close read by the worker model. `partial`: this is one slice of the candidates, so rate every one
    of them (the best are picked across all slices afterwards)."""
    ask = (f"Rate every one of these {len(cands)} candidates" if partial else f"Pick the best {SHORTLIST}")
    res = await ctx.llm.json(
        model=WORKER_MODEL, effort="low" if partial else "medium", system=SYSTEM, schema=Shortlist,
        max_tokens=config.cap("rank_max_tokens"),
        on_retry=ctx.retry_hook("Deal Finder", "ranking the shortlist"),
        prompt=(f"Fund: {reader.fund_name}. Thesis: {dna.model_dump_json()}\n"
                f"Portfolio (id -> name): {dumps(names)}\nKnown rivals of portfolio companies: {dumps(rivals)}\n"
                f"Candidates (scored by our model; model_fit is 0-100): {dumps(cands)}\n\n"
                f"{ask}. For each: company_id (from the candidates), your fit 0-100 "
                "(stay close to model_fit unless the details clearly say otherwise), 2-3 'why' bullets of at "
                "most 12 words each (e.g. 'Like BioOrbit and 2 other health companies they own'), 1-3 signal "
                "chips of 2-4 words (kind: timing = raising or a time-sensitive event, strength = traction "
                "or a link to the portfolio, info = neutral news, risk = a concern), similar_to = the id of "
                "the portfolio company it most looks like (or null), conflict_with = the id of a portfolio "
                "company it directly competes with (or null). "
                + ("Be concise. " if partial else "Spread the picks across the fund's themes: at most 3 picks "
                   "may look like the same portfolio company. ")
                + "Use only facts from the candidate data."))
    return list(res.picks)


async def rank(ctx: RunContext, reader: ReaderResult, dna: FundDNA, scored: ScoreResult,
               mapper: MapperResult) -> FinderResult:
    emit = ctx.emit
    names = {p.company.id: p.company.name for p in reader.portfolio}
    by_id = {c["company_id"]: c for c in scored.top}
    batch = config.cap("rank_batch")
    n_calls = -(-len(scored.top) // batch) if batch and len(scored.top) > batch else 1
    emit.step("Deal Finder", f"Reading the top {len(scored.top)} closely to pick the best {SHORTLIST}"
              + (f", in {n_calls} parallel reads." if n_calls > 1 else "."))
    rivals = {pid: [c.id for c in comps] for pid, comps in mapper.competitors.items()}
    cand_view = []
    for c in scored.top:
        r = dataset.get(c["company_id"])
        if r:
            cand_view.append({**dataset.brief(r), "model_fit": c["fit"], "fit_parts": c["parts"],
                              "looks_like": names.get(c.get("like") or "")})
    groups = ([cand_view[i:i + batch] for i in range(0, len(cand_view), batch)] if n_calls > 1 else [cand_view])
    # Guesses for missing stage / sector run while the candidates are read (Jev is quick, the read is not).
    guesses = asyncio.ensure_future(guess_missing([v["company_id"] for v in cand_view], deadline_s=20.0))
    results = await asyncio.gather(*(_close_read(ctx, reader, dna, names, rivals, g, len(groups) > 1)
                                     for g in groups), return_exceptions=True)
    picks: list[Pick] = []
    failed = 0
    for g, res in zip(groups, results):
        if isinstance(res, LLMUnavailable):
            raise res
        if isinstance(res, BaseException):
            failed += 1
            ids = {v["company_id"] for v in g}
            picks.extend(_fallback_picks(ScoreResult(top=[c for c in scored.top if c["company_id"] in ids]),
                                         names))
            continue
        ids = {v["company_id"] for v in g}
        picks.extend(p for p in res if p.company_id in ids and p.company_id in by_id)
    if failed:
        what = "the close read" if failed == len(groups) else f"{failed} of the {len(groups)} close reads"
        emit.recovered("Deal Finder", f"Couldn't finish {what}, so those candidates use the model's scores and "
                       "simple reasons.", fallback="model scores")
    picks = _best_picks(picks, by_id)
    if len(picks) < min(SHORTLIST, len(by_id)) // 2:
        picks = _fallback_picks(scored, names)
        if not failed:
            emit.recovered("Deal Finder", "Couldn't finish the close read, so the shortlist uses the model's "
                           "scores and simple reasons.", fallback="model scores")

    # Build the deal rows -----------------------------------------------------
    seen = store.get_memory(ctx.fund_id, "seen_companies", {}) or {}
    now = store.now_iso()
    previous = store.get_memory(ctx.fund_id, "page:deals")
    prev_items = {i["company"]["id"]: i for i in (previous or {}).get("items", [])}
    items: list[DealFlowItem] = []
    similar_to: dict[str, str] = {}
    new_ids: list[str] = []
    for p in picks:
        r = dataset.get(p.company_id)
        if not r:
            continue
        c = by_id[p.company_id]
        fit = max(0, min(99, round(0.6 * c["fit"] + 0.4 * max(0, min(100, p.fit)))))
        conflict = p.conflict_with if p.conflict_with in names else None
        if not conflict:  # the Mapper's rivals list also counts as a clash
            conflict = next((pid for pid, ids in rivals.items() if p.company_id in ids), None)
        like = p.similar_to if p.similar_to in names else c.get("like")
        if like in names:
            similar_to[p.company_id] = like
        signals = [Signal(kind=s.kind, label=s.label[:40], icon=icon_for(s.kind, s.label), source_url=None)
                   for s in p.signals[:3]]
        if conflict and not any(s.kind == "risk" for s in signals):
            signals.append(Signal(kind="risk", label=f"Competes with {names[conflict]}", icon="triangle-alert"))
        first = seen.get(p.company_id)
        if not first:
            seen[p.company_id] = now
            new_ids.append(p.company_id)
        status = "new" if not first else (prev_items.get(p.company_id, {}).get("status") or "new")
        items.append(DealFlowItem(
            rank=0, company=dataset.company(r), fit=fit,
            fit_parts=[FitPart(label=k, value=float(v)) for k, v in c["parts"].items()],
            signals=signals[:3], why=[w.strip().rstrip(".") for w in p.why if w.strip()][:3],
            seen_label=seen_label(seen.get(p.company_id)), status=status,  # type: ignore[arg-type]
            conflict_with=conflict, memo_id=None))
    items.sort(key=lambda i: -i.fit)
    store.set_memory(ctx.fund_id, "seen_companies", seen)
    await fill_estimates(ctx, items, guesses)

    # Keep earlier picks (and their human decisions) below this run's shortlist.
    ids = {i.company.id for i in items}
    older = []
    for cid, raw in prev_items.items():
        if cid not in ids:
            old = DealFlowItem.model_validate(raw)
            old.seen_label = seen_label(seen.get(cid))
            older.append(old)
    all_items = (items + older)[:MAX_DEALS_PAGE]
    for i, item in enumerate(all_items, start=1):
        item.rank = i
    counts = DealCounts(all=len(all_items), new=sum(i.status == "new" for i in all_items),
                        under_review=sum(i.status == "under_review" for i in all_items),
                        passed=sum(i.status == "passed" for i in all_items))
    data.save_page(ctx.fund_id, "deals", DealsResponse(fund_id=ctx.fund_id, counts=counts, items=all_items))

    # Feed ------------------------------------------------------------------
    for item in items[:3]:
        like = similar_to.get(item.company.id)
        extra = f" It looks like {names[like]}, which {reader.fund_name} already owns." if like else ""
        first = "Strong match" if item is items[0] else "New match"
        emit.finding("Deal Finder", f"{first}: {item.company.name}, {item.company.one_liner[:80].rstrip('.')}.{extra}",
                     tag="New match", company_id=item.company.id, fit=item.fit)
    for item in items:
        if item.conflict_with:
            emit.warning("Deal Finder", f"{item.company.name} fits at {item.fit}%, but it competes with "
                         f"{names[item.conflict_with]}. Flagged as a clash.", tag="Clash",
                         company_id=item.company.id, conflict_with=item.conflict_with, fit=item.fit)
    mix = mix_label(items).replace(" · no founder traits used", "").replace(" · ", ", ")
    emit.done("Deal Finder", f"Shortlist ready: {len(items)} startups ranked by fit. {mix}.",
              **plan("deals", "done"))
    return FinderResult(deals=items, similar_to=similar_to, new_ids=new_ids)


def set_memo_id(fund_id: str, company_id: str, memo_id: str) -> None:
    """Point the deal row (and the map's shortlist) at the memo once it exists."""
    for page in ("deals", "map"):
        raw = store.get_memory(fund_id, f"page:{page}")
        if not raw:
            continue
        rows = raw["items"] if page == "deals" else raw["shortlist"]
        for row in rows:
            if row["company"]["id"] == company_id:
                row["memo_id"] = memo_id
        store.set_memory(fund_id, f"page:{page}", raw)
