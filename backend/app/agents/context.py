"""Shared state for one live run: the emitter, the model client, checkpoints, sources and the page budget.

    ctx = RunContext(run_id, fund_id, url, task, emit, llm)
    reader_out = await ctx.stage("read", ReaderResult, lambda: reader.run(ctx))   # checkpointed
    page = await ctx.fetch("Reader", url, "the portfolio page")                   # retries + plain-English events

Checkpoints live in SQLite (`memory` table, key `ckpt:<run_id>:<stage>`). When the server restarts during a
live run, the run resumes: finished stages are loaded instead of re-run, and the feed shows "Recovered".
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional, TypeVar

from pydantic import BaseModel

from .. import store
from ..tools import jev, web
from .llm import LLM

log = logging.getLogger("bellwether.agents")

T = TypeVar("T", bound=BaseModel)

# The fixed stages of a run, in plan order (1-based plan_step = index + 1).
STAGES = ["read", "thesis", "market", "map", "deals", "memo", "check"]
STAGE_LABELS = {"read": "the website reading", "thesis": "the fund's thesis", "market": "the news check",
                "map": "the market map", "deals": "the shortlist", "memo": "the memo", "check": "the fact-check",
                "competitors": "the competitor search", "scores": "the scores"}
FETCH_ATTEMPTS = 3
MAX_STAGE_RESUMES = 3  # restarts allowed per stage before it finishes with partial data
FETCH_BACKOFF_S = 1.5  # tests set this to 0


def plan(stage: str, status: str) -> dict:
    """data fields that tick the Research page checklist: {"plan_step": n, "plan_status": status}."""
    return {"plan_step": STAGES.index(stage) + 1, "plan_status": status}


class StageFailed(Exception):
    """A stage couldn't produce anything usable. The message is plain English."""


class RunContext:
    def __init__(self, run_id: str, fund_id: str, url: str, task: str, emit: Any, llm: LLM, *,
                 resumed: bool = False, max_pages: int = 30):
        self.run_id = run_id
        self.fund_id = fund_id
        self.url = url
        self.task = task
        self.emit = emit
        self.llm = llm
        self.resumed = resumed
        self.pages = web.PageBudget(max_pages)
        self.fund_name = fund_id.replace("-", " ").title()
        self.injection_warned: set[str] = set()
        self.stage_starts: dict[str, int] = {}
        self.screened: list[str] = []  # pages Jev checked for instructions aimed at an AI

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------

    def _ckpt_key(self, name: str) -> str:
        return f"ckpt:{self.run_id}:{name}"

    def load_checkpoint(self, name: str, model: type[T]) -> Optional[T]:
        raw = store.get_memory(self.fund_id, self._ckpt_key(name))
        if raw is None:
            return None
        try:
            return model.model_validate(raw)
        except Exception:  # a checkpoint from an older shape: just redo the stage
            return None

    def save_checkpoint(self, name: str, value: BaseModel) -> None:
        store.set_memory(self.fund_id, self._ckpt_key(name), value.model_dump(mode="json"))

    async def stage(self, name: str, model: type[T], run: Callable[[], Awaitable[T]], agent: str = "Partner") -> T:
        """Run a stage once. If a checkpoint exists (after a restart), reuse it and say so in the feed."""
        saved = self.load_checkpoint(name, model)
        if saved is not None:
            label = STAGE_LABELS.get(name, name)
            self.emit.recovered(agent, f"Picked up {label} saved before the restart, so it isn't redone.",
                                fallback="checkpoint", **(plan(name, "done") if name in STAGES else {}))
            return saved
        # Count starts of this stage across restarts. After MAX_STAGE_RESUMES the stage should finish with
        # what it already has (the Reader reads only cached pages) instead of looping forever.
        key = self._ckpt_key(f"{name}:starts")
        starts = int(store.get_memory(self.fund_id, key) or 0) + 1
        store.set_memory(self.fund_id, key, starts)
        self.stage_starts[name] = starts
        if starts > MAX_STAGE_RESUMES + 1:
            self.emit.warning(agent, f"Restarted {starts - 1} times while working on "
                              f"{STAGE_LABELS.get(name, name)}. Finishing with what I already have.")
        result = await run()
        self.save_checkpoint(name, result)
        return result

    def out_of_resumes(self, name: str) -> bool:
        return self.stage_starts.get(name, 1) > MAX_STAGE_RESUMES + 1

    # ------------------------------------------------------------------
    # Retry hooks that speak plain English in the feed
    # ------------------------------------------------------------------

    def retry_hook(self, agent: str, what: str) -> Callable[[int, str], None]:
        def hook(attempt: int, reason: str) -> None:
            self.emit.warning(agent, f"{reason[0].upper() + reason[1:]} while {what}. Trying again.",
                              attempt=attempt)
        return hook

    # ------------------------------------------------------------------
    # Web pages with retries, a page budget and the prompt-injection guard
    # ------------------------------------------------------------------

    async def fetch(self, agent: str, url: str, label: str, *, quiet: bool = False,
                    max_bytes: int = web.MAX_BYTES) -> Optional[web.Page]:
        """Read a page with up to 3 tries. Returns None when it can't be read (the caller picks a fallback).

        Emits: a `tool` event (unless quiet), `warning` events on retries, and a `warning` if the page
        contains text that looks like instructions to an AI (which is ignored).

        Before any agent reads the page, Jev checks it piece by piece for text aimed at an AI. What it is
        fairly sure about (single lines where it can tell) is cut out of `page.text`. Without Jev, the
        pattern check in tools/web flags such text instead.
        """
        if not quiet:
            self.emit.tool(agent, "fetch_page", f"Opening {label}.", url=url)
        for attempt in range(1, FETCH_ATTEMPTS + 1):
            try:
                self.pages.take()
                page = await web.fetch_page(url, max_bytes=max_bytes)
            except web.FetchError as exc:
                if exc.retryable and attempt < FETCH_ATTEMPTS:
                    first = "took too long to load" if str(exc) == "took too long to load" else str(exc)
                    msg = (f"{label[0].upper() + label[1:]} {first}. Trying again." if attempt == 1
                           else "The second try didn't work either. One more go.")
                    self.emit.warning(agent, msg, url=url, attempt=attempt)
                    await asyncio.sleep(FETCH_BACKOFF_S * attempt)
                    continue
                if attempt > 1 or not exc.retryable:
                    self.emit.warning(agent, f"{label[0].upper() + label[1:]} {exc}.", url=url,
                                      attempt=attempt)
                return None
            except Exception:  # never let one page crash the run
                log.exception("fetch failed: %s", url)
                return None
            await self.screen_page(agent, page)
            return page
        return None

    async def screen_page(self, agent: str, page: web.Page) -> None:
        """Prompt-injection check with Jev; strips flagged parts. Falls back to the pattern check."""
        scan = None
        try:
            scan = await jev.injection_scan(page.final_url, page.text)
        except Exception:  # an optional check must never break a run
            log.exception("injection scan failed")
        if scan is None:
            self.check_injection(agent, page.final_url, page.suspicious)
            return
        self.screened.append(page.final_url)
        if scan.flagged:
            removed = scan.flagged_text()
            page.text = scan.cleaned()
            page.suspicious = removed + web.suspicious_lines(page.text)  # what is left still counts
            self.check_injection(agent, page.final_url, page.suspicious, removed=len(removed),
                                 likelihood=round(scan.top, 2))
        else:
            self.check_injection(agent, page.final_url, page.suspicious)

    def check_injection(self, agent: str, url: str, suspicious: list[str], *, removed: int = 0,
                        likelihood: float | None = None) -> None:
        if suspicious and url not in self.injection_warned:
            self.injection_warned.add(url)
            extra = {"removed_parts": removed, "likelihood": likelihood, "checked_by": "Jev"} if removed else {}
            what = ("I cut it out before reading the page" if removed
                    else "I ignored it and only used the page as information")
            self.emit.warning(agent, f"Found text on {web.host_of(url)} that tries to give instructions to an "
                              f"AI. {what}.", tag=None, url=url, ignored_instructions=True, **extra)
