"""Critic: checks every memo claim against its source and marks it verified or not.

Unsupported claims stay in the memo, marked "not verified" (never hidden). Also fills the "Can you trust
this memo?" block. Model: the worker model (MODEL_WORKER). If the check can't run, every claim stays
"not verified".

Two independent checks are combined:
1. Claude reads every claim with its source and says supported or not (plus bias / conflict concerns).
2. Jev answers, per claim, "does `source_text` support `claim`?" as a probability.
A claim is verified only when it has a source and both agree (Jev not clearly against). If Claude's check
fails, Jev alone decides, with a higher bar. If neither runs, every claim stays "not verified".
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from .. import config
from ..models import DealFlowItem, Memo
from ..tools import jev, web
from .analyst import AnalystResult, SourceDoc
from .context import RunContext, plan
from .llm import WORKER_MODEL, LLMError, LLMUnavailable

NL = chr(10)
MAX_REFETCH = 4
JEV_AGREE = 0.4  # with Claude's "supported": Jev must not be clearly against
JEV_ALONE = 0.75  # when Claude's check failed: Jev alone must be fairly sure


class ClaimCheck(BaseModel):
    claim: int  # index in the list given
    supported: bool
    note: str


class CriticReport(BaseModel):
    checks: list[ClaimCheck]
    concerns: list[str]  # bias, conflicts of interest, over-confident wording


SYSTEM = (
    "You are Critic, part of Bellwether, a research assistant for a venture capital fund. You check a memo "
    "claim by claim. A claim is supported only if its own source clearly says it; anything stronger than the "
    "source, or not in it, is unsupported. Also flag bias (e.g. judging founders by personal traits), "
    "conflicts with the fund's portfolio and over-confident wording. " + web.UNTRUSTED_RULES
)


async def _refetch_thin_sources(ctx: RunContext, memo: Memo, docs: dict[str, SourceDoc]) -> None:
    """Open cited pages we only know from a search title, so the check reads the real page."""
    cited = {c.source.url for s in memo.sections for c in s.claims if c.source and c.source.url}
    todo = [d for d in docs.values() if d.url in cited and not d.fetched][:MAX_REFETCH]

    async def refetch(doc: SourceDoc) -> None:  # all at once
        page = await ctx.fetch("Critic", doc.url, web.host_of(doc.url) or "a source", quiet=True)
        if page is not None:
            doc.text = page.text[:12_000]
            doc.fetched = True

    await asyncio.gather(*(refetch(d) for d in todo))


async def run(ctx: RunContext, analyst: AnalystResult, pick: DealFlowItem, conflict_name: str | None) -> Memo:
    emit = ctx.emit
    memo = analyst.memo.model_copy(deep=True)
    emit.tool("Critic", "fetch_page", "Checking each claim against its source.", memo_id=memo.id,
              **plan("check", "working"))
    docs = {d.url or f"row:{d.row_id}": d for d in analyst.docs}
    await _refetch_thin_sources(ctx, memo, docs)

    claims = [c for s in memo.sections for c in s.claims]
    items, by_key = [], {}
    for d in analyst.docs:
        by_key[(d.url, d.row_id)] = d
    claim_docs: list[SourceDoc | None] = []
    for i, c in enumerate(claims):
        src = c.source
        doc = by_key.get((src.url, src.row_id)) if src else None
        if src and doc is None:
            doc = next((d for d in analyst.docs if (src.url and d.url == src.url) or
                        (src.row_id and d.row_id == src.row_id)), None)
        claim_docs.append(doc if src else None)
        items.append({"claim": i, "text": c.text,
                      "source": web.wrap_untrusted(doc.url or doc.label, doc.text, 4000, label="untrusted_source")
                      if doc else "NO SOURCE"})

    # Second opinion from Jev: all claims in one call (runs alongside Claude's check).
    jev_task = asyncio.ensure_future(jev.claim_support(
        [(c.text, d.text if d else "") for c, d in zip(claims, claim_docs)]))

    checked = False
    concerns: list[str] = []
    llm_verdict: list[bool | None] = [None] * len(claims)
    try:
        report = await ctx.llm.json(
            model=WORKER_MODEL, effort="low" if config.cap("critic_effort_low") else "medium", system=SYSTEM,
            schema=CriticReport, max_tokens=config.cap("critic_max_tokens"),
            on_retry=ctx.retry_hook("Critic", "checking the memo"),
            prompt=(f"Memo about {memo.company.name}. For every claim, decide if its source supports it. "
                    "Claims with NO SOURCE are unsupported." + NL + NL + (NL + NL).join(
                        f"Claim {it['claim']}: {it['text']}" + NL + "Source:" + NL + it["source"]
                        for it in items)))
        verdicts = {ck.claim: ck for ck in report.checks}
        llm_verdict = [bool(verdicts[i].supported) if i in verdicts else False for i in range(len(claims))]
        concerns = [x for x in report.concerns if x.strip()][:3]
        checked = True
    except LLMUnavailable:
        jev_task.cancel()
        raise
    except LLMError:
        pass
    except BaseException:
        jev_task.cancel()
        raise
    try:
        jev_probs = await jev_task
    except Exception:
        jev_probs = [None] * len(claims)

    for i, c in enumerate(claims):
        jp = jev_probs[i]
        if not c.source:
            c.verified = False
        elif checked:
            c.verified = bool(llm_verdict[i]) and (jp is None or jp >= JEV_AGREE)
        else:  # Claude's check failed: Jev alone, with a higher bar
            c.verified = jp is not None and jp >= JEV_ALONE
    judged = [i for i, p in enumerate(jev_probs) if p is not None]
    if judged:
        if checked:
            agree = sum(1 for i in judged if (jev_probs[i] >= 0.5) == bool(llm_verdict[i]))
            msg = (f"A second checker (Jev) read {len(judged)} claims against their sources and agreed with "
                   f"the first check on {agree} of them.")
        else:
            agree = 0
            msg = (f"The main fact-check didn't finish, so a second checker (Jev) read {len(judged)} claims "
                   "against their sources on its own.")
        emit.step("Critic", msg, checker="Jev", claims_judged=len(judged), agreed=agree, memo_id=memo.id)
        checked = True
    if not checked:
        emit.warning("Critic", "Couldn't finish the fact-check, so every claim is marked as not verified.",
                     tag="Not verified", memo_id=memo.id)

    unverified = [c for c in claims if not c.verified]
    if checked:
        for c in unverified[:3]:
            short = c.text if len(c.text) <= 90 else c.text[:87] + "..."
            emit.warning("Critic", f"Couldn't confirm: \"{short}\" Marked it as not verified.", tag="Not verified",
                         memo_id=memo.id)
    with_source = sum(1 for c in claims if c.source)
    memo.trust.claims_with_source = with_source
    memo.trust.claims_total = len(claims)
    memo.trust.checked_by_critic = checked
    memo.trust.not_verified = len(unverified)
    memo.trust.conflicts = [f"Competes with {conflict_name}"] if conflict_name else []
    emit.finding("Critic", f"Checked the memo: {with_source} of {len(claims)} claims have a source. "
                 f"{len(unverified)} marked as not verified.", memo_id=memo.id,
                 claims_with_source=with_source, claims_total=len(claims))
    clash = f"Flagged a clash: it competes with {conflict_name}." if conflict_name else "No clashes with the portfolio."
    emit.done("Critic", f"{clash} Founder traits were not used.", memo_id=memo.id, concerns=concerns,
              **plan("check", "done"))
    return memo


__all__ = ["run", "CriticReport"]
