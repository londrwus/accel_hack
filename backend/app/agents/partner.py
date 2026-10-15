"""Partner: the orchestrator (MODEL_ORCHESTRATOR). Plans the run, hands work to the team, writes the summary.

Flow (each stage is checkpointed, so a restarted run resumes where it stopped):

    plan -> Reader -> Thesis -> (Mapper competitors || Deal Finder scoring) -> shortlist -> Market Map
         -> Analyst memo -> Critic check -> watch diff -> summary -> done
    Market news starts after the Reader and runs in the background: nothing waits on it except the memo (a few
    seconds at most); the Portfolio page gets its news chips when it lands.

Modal is warmed at the very start. How much each stage does comes from RUN_PROFILE (config.PROFILES).

The order is fixed in code (simple and reliable); the orchestrator model writes the plan wording and the final summary.
Humans decide: nothing here contacts founders, sends anything or commits money.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from pydantic import BaseModel

from .. import config, data, store
from ..models import FundDNA, Memo
from ..runs import DEFAULT_PLAN
from . import analyst, critic, enricher, finder, mapper, market, ml, portfolio, reader, thesis, watch
from .context import STAGES, RunContext
from .llm import ORCHESTRATOR_MODEL, LLMError, LLMUnavailable, dumps

log = logging.getLogger("bellwether.partner")


class PartnerPlan(BaseModel):
    opening: str  # one sentence for the feed
    steps: list[str]  # exactly 7 short labels, one per fixed stage


class PartnerSummary(BaseModel):
    summary: str


SYSTEM = (
    "You are Partner, the lead of Bellwether, a team of AI analysts working for a venture capital fund. You "
    "plan the work and report back to a human investor in plain, friendly English (no jargon, no hype). The "
    "system only recommends: a person makes every decision, and nobody is ever contacted."
)


class Results(BaseModel):
    """Everything a run produced (also what `write_memo` reuses)."""

    read: reader.ReaderResult
    dna: FundDNA
    news: market.MarketResult


async def make_plan(ctx: RunContext) -> list[str]:
    try:
        p = await ctx.llm.json(
            model=ORCHESTRATOR_MODEL, effort="low", system=SYSTEM, schema=PartnerPlan,
            on_retry=ctx.retry_hook("Partner", "planning"),
            prompt=(f"The user asked: {ctx.task!r} for the fund at {ctx.url}.\nYour team will do these 7 stages in "
                    f"this order: {dumps(DEFAULT_PLAN)}.\nWrite each stage as a short checklist label (3-6 "
                    "words, plain English, same order, exactly 7), and one opening sentence for the activity "
                    "feed saying what you'll start with."))
        steps = [s.strip() for s in p.steps if s.strip()]
        if len(steps) != len(STAGES):
            raise LLMError("wrong number of steps")
        opening = p.opening.strip()
    except LLMUnavailable:
        raise
    except LLMError:
        steps, opening = list(DEFAULT_PLAN), "Starting with the fund's website."
    ctx.emit.plan(steps, message=f"Made a {len(steps)}-step plan. {opening}")
    return steps


def memo_pick(deals: list) -> Optional[object]:
    """The deal the memo is written on: the best fit that doesn't compete with a company the fund owns.
    If every deal clashes, the best fit anyway (the memo then flags the clash)."""
    if not deals:
        return None
    return next((d for d in deals if not d.conflict_with), deals[0])


async def summarize(ctx: RunContext, res: Results, deals: finder.FinderResult, memo: Optional[Memo],
                    since: Optional[str]) -> str:
    top = memo_pick(deals.deals)
    facts = {"fund": res.read.fund_name, "thesis": res.dna.summary, "portfolio_size": len(res.read.portfolio),
             "top_pick": top.company.name if top else None, "top_fit": top.fit if top else None,
             "shortlist_size": len(deals.deals),
             "best_five_on_shortlist": [d.company.name for d in deals.deals[:5]],
             "clashes": [d.company.name for d in deals.deals if d.conflict_with],
             "memo_claims": memo.trust.claims_total if memo else 0,
             "not_verified": memo.trust.not_verified if memo else 0, "changes": since}
    try:
        s = await ctx.llm.json(
            model=ORCHESTRATOR_MODEL, effort="low", system=SYSTEM, schema=PartnerSummary,
            on_retry=ctx.retry_hook("Partner", "writing the summary"),
            prompt=(f"Write a 2-3 sentence summary of this run for the investor: {dumps(facts)}. Mention the top "
                    "pick and why, anything not verified, and that they make the call."))
        return s.summary.strip()
    except LLMUnavailable:
        raise
    except LLMError:
        if top:
            return (f"{top.company.name} is the best fit for {res.read.fund_name} at {top.fit}%. "
                    f"The memo is ready to review; you make the call.")
        return f"I read {res.read.fund_name}'s website and wrote down its thesis. You make the call."


async def run_team(ctx: RunContext) -> None:
    emit = ctx.emit
    if not ctx.resumed:
        emit.step("Partner", f"Starting a run on {ctx.url.split('://')[-1].rstrip('/')}.")
    warm = asyncio.ensure_future(ml.warm_up())  # start both Modal models now, so they're warm when needed
    steps = store.get_memory(ctx.fund_id, f"ckpt:{ctx.run_id}:plan")
    if not steps:
        steps = await make_plan(ctx)
        store.set_memory(ctx.fund_id, f"ckpt:{ctx.run_id}:plan", steps)

    # 1. Read the website ------------------------------------------------------------------
    rd = await ctx.stage("read", reader.ReaderResult, lambda: reader.run(ctx), agent="Reader")
    ctx.fund_name = rd.fund_name
    if ctx.screened:
        n = len(ctx.screened)
        emit.step("Reader", f"Checked {n} {'page' if n == 1 else 'pages'} for hidden text that tries to give "
                  f"instructions to an AI before reading {'it' if n == 1 else 'them'}"
                  + (". Nothing like that was found." if not ctx.injection_warned else "."),
                  checked_by="Jev", pages_checked=n)

    # 2 + 3. Thesis now; the news check runs in the background (nothing waits on it until the memo) ---------
    market_task = asyncio.ensure_future(
        ctx.stage("market", market.MarketResult, lambda: market.run(ctx, rd), agent="Market"))
    # Profiles for the portfolio companies, in parallel workers (never blocks the deals or the memo).
    enrich_tasks = [_background(enricher.run(ctx, rd.fund_url, [p.company for p in rd.portfolio]))]
    emit.step("Partner", "Fanned out the team in parallel: Thesis, Market and a group of Enricher workers "
              "are now running at the same time.", parallel=["Thesis", "Market", "Enricher"])
    try:
        found, mp, dna = await _after_reading(ctx, rd, steps)
        mk = await _news_or_empty(market_task, wait_s=config.cap("market_wait_s"))
    except BaseException:
        market_task.cancel()
        raise

    enrich_tasks.append(_background(enricher.run(ctx, rd.fund_url, [d.company for d in found.deals],
                                                 what="shortlisted")))

    # 6 + 7. Memo for the top pick, then the fact-check ------------------------------------
    memo: Optional[Memo] = None
    if found.deals:
        top = memo_pick(found.deals)
        names = {p.company.id: p.company.name for p in rd.portfolio}
        if top is not found.deals[0]:
            best = found.deals[0]
            emit.step("Partner", f"{best.company.name} fits best but competes with "
                      f"{names.get(best.conflict_with or '', 'a company the fund owns')}, so the memo is on "
                      f"{top.company.name}, the best fit with no clash.", company_id=top.company.id)
        news = _news_about(mk, top.company.name) if mk else []
        try:
            drafted = await ctx.stage(
                "memo", analyst.AnalystResult,
                lambda: analyst.run(ctx, top, dna, rd.fund_name, rd.fund_url, found.similar_to.get(top.company.id),
                                    news),
                agent="Analyst")
            memo = await ctx.stage(
                "check", Memo, lambda: critic.run(ctx, drafted, top, names.get(top.conflict_with or "")),
                agent="Critic")
            data.save_memo(ctx.fund_id, memo)
            finder.set_memo_id(ctx.fund_id, top.company.id, memo.id)
        except LLMUnavailable:
            market_task.cancel()
            raise
        except LLMError as exc:
            emit.error("Analyst", f"Couldn't write the memo this time ({exc}). The shortlist is still ready.",
                       reason="memo_failed")
    else:
        emit.warning("Deal Finder", "No startups matched well enough for a memo.", tag=None)

    # The news check has had plenty of time by now: fold it into the Portfolio page.
    if mk is None:
        mk = await _news_or_empty(market_task, wait_s=float(config.cap("market_cap_s")) + 15)
    if not market_task.done():
        market_task.cancel()
    mk = mk or market.MarketResult()
    page, health = portfolio.build(ctx.fund_id, rd, mk)
    data.save_page(ctx.fund_id, "portfolio", page)
    res = Results(read=rd, dna=dna, news=mk)

    # Watch mode: what changed since last time -------------------------------------------------
    competitors = [c.id for comps in mp.competitors.values() for c in comps]
    since = watch.report(ctx, watch.snapshot(found.deals, health, mk, competitors, ctx.run_id))

    summary = await summarize(ctx, res, found, memo, since)
    emit.set_state(partner_summary=summary, **({"since_last_run": since} if since else {}))
    watching = (store.get_watch(ctx.fund_id) or {}).get("enabled")
    tail = " I'll check again tomorrow at 7am and tell you what changed." if watching else " You make the call."
    if not warm.done():
        warm.cancel()
    await asyncio.wait(enrich_tasks, timeout=config.cap("enrich_wait_s"))  # a little time to finish; the rest carries on afterwards
    if not all(t.done() for t in enrich_tasks):
        emit.step("Enricher", "Still filling in company profiles in the background; pages update as they land.")
    emit.done("Partner", f"Done. {summary.split('. ')[0].rstrip('.')}.{tail}", run_done=True,
              **({"memo_id": memo.id} if memo else {}))


async def _after_reading(ctx: RunContext, rd: reader.ReaderResult, steps: list[str]):
    """Thesis, then Deal Finder and Mapper side by side (they start the moment the thesis is ready)."""
    emit = ctx.emit
    dna = await ctx.stage("thesis", FundDNA, lambda: thesis.run(ctx, rd), agent="Thesis")
    emit.step("Partner", "The fund's thesis is ready. Starting the deal search while the news check finishes.")
    # A first Portfolio page straight away (news chips are added when the news check is done).
    page, _ = portfolio.build(ctx.fund_id, rd, market.MarketResult())
    data.save_page(ctx.fund_id, "portfolio", page)

    # 4 + 5. Competitors and scoring in parallel, then the shortlist and the map ------------
    emit.handoff("Thesis", ["Deal Finder", "Mapper"], "Handed the fund's thesis to Deal Finder and Mapper.",
                 "Fund DNA", plan_step=4, plan_status="working")
    mp, scored = await asyncio.gather(
        ctx.stage("competitors", mapper.MapperResult, lambda: mapper.find_competitors(ctx, rd), agent="Mapper"),
        ctx.stage("scores", finder.ScoreResult, lambda: finder.score(ctx, rd, dna), agent="Deal Finder"))
    found = await ctx.stage("deals", finder.FinderResult, lambda: finder.rank(ctx, rd, dna, scored, mp),
                            agent="Deal Finder")
    mapper.build_map(ctx, rd, mp, found.deals, found.similar_to)
    return found, mp, dna


def _background(coro) -> "asyncio.Future":
    """Start optional work that must never fail the run."""
    task = asyncio.ensure_future(coro)

    def _done(t: "asyncio.Future") -> None:
        if not t.cancelled() and t.exception() is not None:
            log.warning("background enrichment failed: %s", type(t.exception()).__name__)
    task.add_done_callback(_done)
    return task


async def _news_or_empty(task: "asyncio.Future", wait_s: float) -> Optional[market.MarketResult]:
    """The news check's result if it finishes within `wait_s`, else None (it keeps running)."""
    if not task.done():
        await asyncio.wait({task}, timeout=wait_s)
    if not task.done() or task.cancelled():
        return None
    exc = task.exception()
    if isinstance(exc, LLMUnavailable):
        raise exc
    if exc is not None:  # the news check is optional: carry on without it
        log.warning("news check failed: %s", type(exc).__name__)
        return None
    return task.result()


def _news_about(mk: market.MarketResult, company: str) -> list[dict]:
    """News items from the Market check that name this company (passed to the Analyst as sources)."""
    low = company.lower()
    out = [{"text": h.text, "url": h.url} for h in mk.highlights if h.url and low in h.text.lower()]
    out += [{"text": f"{r.company} raised" + (f" a {r.round}" if r.round else " money") + ".", "url": r.url}
            for r in mk.other_raises if r.url and r.company.lower() == low]
    return out
