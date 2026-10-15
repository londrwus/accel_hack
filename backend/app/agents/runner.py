"""Live run entry points, called by app.runs and app.main.

    await run_live(run_id, url, emit, fund_id=..., task=...)       # the whole analyst team
    memo = await write_memo(run_id, fund_id, company_id, emit)      # one memo on demand

Behaviour (see app.runs._run_main for what happens around these):
- No ANTHROPIC_API_KEY -> raises LLMUnavailable(reason="no_api_key"); the run ends with a clear Partner error.
- Key rejected -> LLMUnavailable(reason="bad_api_key"), same.
- No network before anything was produced -> LLMUnavailable(reason="no_connection"); the run falls back to
  the recorded replay so the demo keeps going.
- A stage that can't produce anything (e.g. the fund can't be found at all) -> Partner error, plain English.
- After a server restart, a live run resumes from its checkpoints (state.resumed = True).
Everything the team finds is saved with app.data.save_page / save_memo / save_scores, so the page
endpoints serve it instead of the mocks. Nothing here contacts founders, sends anything or commits money.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from .. import config, data, store
from ..models import FundDNA
from ..tools import web
from .context import RunContext, StageFailed
from .llm import EXTRACT_MODEL, LLM, ORCHESTRATOR_MODEL, WORKER_MODEL, LLMError, LLMUnavailable

if TYPE_CHECKING:
    from app.models import Memo
    from app.runs import Emitter

log = logging.getLogger("bellwether.runner")

__all__ = ["run_live", "write_memo", "write_top_memos", "ORCHESTRATOR_MODEL", "WORKER_MODEL", "EXTRACT_MODEL", "LLMUnavailable"]

# Tests (or a future multi-client setup) can swap the model client here.
_llm_factory = LLM


def _require_key() -> None:
    if not config.llm_key():
        raise LLMUnavailable("No Anthropic API key is set, so the live agents can't start.", reason="no_api_key")


async def run_live(run_id: str, url: str, emit: "Emitter", *, fund_id: str = "", task: str = "",
                   llm: Optional[Any] = None) -> None:
    """Run the live analyst team for one fund URL."""
    if llm is None:
        _require_key()
        llm = _llm_factory()
    run = store.get_run(run_id) or {}
    resumed = bool((run.get("state") or {}).get("resumed"))
    ctx = RunContext(run_id, fund_id or data.fund_id_from_url(url), web.normalize_url(url), task, emit, llm,
                     resumed=resumed)
    from .partner import run_team  # local import keeps app.runs -> agents import light
    try:
        await run_team(ctx)
    except StageFailed as exc:
        emit.error("Partner", f"{exc} The run stopped here. Earlier results are safe.", reason="stage_failed")
    finally:
        _log_usage(run_id)


def _log_usage(run_id: str) -> None:
    """Token totals for this process so far (Claude per model id, and Jev), for cost checks."""
    from ..tools import jev
    from .llm import USAGE
    log.info("usage after %s: claude=%s jev=%s", run_id, USAGE, dict(jev.usage))


async def write_memo(run_id: str, fund_id: str, company_id: str, emit: "Emitter",
                     llm: Optional[Any] = None) -> Optional["Memo"]:
    """On-demand memo for GET /api/runs/{id}/memo/{company_id}. Returns None if it can't be written."""
    from . import analyst, critic

    pick = data.deal_item(fund_id, company_id)
    raw_dna = store.get_memory(fund_id, "fund_dna")
    if raw_dna is None:  # seeded funds keep the thesis on the fund page only
        saved = data.get_fund(fund_id).dna if store.get_memory(fund_id, "page:fund") else None
        raw_dna = saved.model_dump(mode="json") if saved else None
    if pick is None or raw_dna is None:
        log.warning("no memo for %s/%s: %s", fund_id, company_id, "no deal row" if pick is None else "no thesis")
        return None
    try:
        if llm is None:
            _require_key()
            llm = _llm_factory()
        run = store.get_run(run_id) or {}
        fund = data.get_fund(fund_id, run.get("fund_url"))
        ctx = RunContext(run_id, fund_id, fund.url, run.get("task", ""), emit, llm)
        ctx.fund_name = fund.name
        dna = FundDNA.model_validate(raw_dna)
        rivals = {}
        page = store.get_memory(fund_id, "page:portfolio") or {}
        for col in page.get("columns", []):
            for it in col.get("items", []):
                rivals[it["company"]["id"]] = it["company"]["name"]
        drafted = await analyst.run(ctx, pick, dna, fund.name, fund.url)
        memo = await critic.run(ctx, drafted, pick, rivals.get(pick.conflict_with or "") or pick.conflict_with)
        from .finder import set_memo_id
        set_memo_id(fund_id, company_id, memo.id)
        return memo
    except (LLMError, StageFailed) as exc:
        log.warning("memo for %s/%s failed: %s", fund_id, company_id, exc)
        return None


async def write_top_memos(run_id: str, fund_id: str, emit: "Emitter", top: int = 5,
                          llm: Optional[Any] = None) -> list["Memo"]:
    """Memos for the current top `top` deals that don't have one yet: Analyst + Critic per deal, 3 at a time."""
    import asyncio
    from ..models import DealsResponse
    from .context import EXTRA_MEMO

    try:
        deals = data._page(fund_id, "deals", DealsResponse).items[:max(1, top)]
    except data.NoData:
        return []
    missing = [d for d in deals if data.memo(fund_id, d.company.id) is None]
    log.info("top memos for %s: writing %s", fund_id, [d.company.id for d in missing])
    if not missing:
        return []
    if llm is None:
        _require_key()
        llm = _llm_factory()
    emit.step("Partner", f"Writing memos for {len(missing)} more of the top deals in parallel: "
              + ", ".join(d.company.name for d in missing) + ".", parallel=["Analyst", "Critic"])
    sem = asyncio.Semaphore(3)

    async def one(d) -> Optional["Memo"]:
        async with sem:
            EXTRA_MEMO.set(True)
            try:
                memo = await write_memo(run_id, fund_id, d.company.id, emit, llm=llm)
            except Exception as exc:  # one failed memo must never stop the others
                log.warning("memo for %s failed: %s", d.company.id, type(exc).__name__)
                memo = None
            if memo is not None:
                data.save_memo(fund_id, memo)
            return memo

    done = [m for m in await asyncio.gather(*(one(d) for d in missing)) if m is not None]
    emit.step("Partner", f"{len(done)} more {'memo is' if len(done) == 1 else 'memos are'} ready to review "
              "on the Investment Memos page.")
    return done
