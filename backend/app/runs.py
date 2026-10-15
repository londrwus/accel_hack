"""Runs: start, emit events, replay recordings, build RunState, stream SSE.

Live runs: app.agents.runner.run_live (the analyst team). Replay: a recorded event log.

Every event goes through `Emitter.__call__` -> SQLite (`store.append_event`) -> wakes SSE listeners.
`emit` is thread-safe, so live agents can call it from asyncio tasks or from worker threads.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from . import config, data, store
from .models import AgentEvent, AgentStatus, PlanStep, RunState

log = logging.getLogger("bellwether.runs")

AGENTS = ["Partner", "Reader", "Thesis", "Market", "Mapper", "Deal Finder", "Analyst", "Critic", "Enricher"]
DEFAULT_PLAN = ["Read the website", "Write the fund’s thesis", "Check the news",
                "Map portfolio & competitors", "Find the next 10 deals", "Write the memo",
                "Fact-check it"]
PING_EVERY_S = 15.0

# ---------------------------------------------------------------------------
# Wake-up signals for SSE listeners (one asyncio.Event per run, replaced on every emit)
# ---------------------------------------------------------------------------

_loop: Optional[asyncio.AbstractEventLoop] = None
_signals: dict[str, asyncio.Event] = {}
_tasks: dict[str, asyncio.Task] = {}


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def _signal(run_id: str) -> asyncio.Event:
    ev = _signals.get(run_id)
    if ev is None:
        ev = _signals[run_id] = asyncio.Event()
    return ev


def _wake(run_id: str) -> None:
    ev = _signals.pop(run_id, None)
    if ev is not None:
        ev.set()


def _notify(run_id: str) -> None:
    if _loop is None:
        return
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is _loop:
        _wake(run_id)
    else:
        try:
            _loop.call_soon_threadsafe(_wake, run_id)
        except RuntimeError:  # the server loop is closed (e.g. a script or test using its own loop)
            pass


def is_final(event: dict) -> bool:
    return event["agent"] == "Partner" and (
        (event["type"] == "done" and bool(event["data"].get("run_done"))) or event["type"] == "error")


# ---------------------------------------------------------------------------
# Emitter: the one way to write an event
# ---------------------------------------------------------------------------


class Emitter:
    """Bound to one run. Call it like `emit("Reader", "tool", "Opening localglobe.vc.", data={...})`.

    Returns the stored AgentEvent. A Partner `done` with data.run_done=True (or a Partner `error`)
    finishes the run and closes every open stream.
    """

    def __init__(self, run_id: str):
        self.run_id = run_id

    def __call__(self, agent: str, type: str, message: str, *, tag: str | None = None,
                 data: dict[str, Any] | None = None, elapsed_s: float | None = None) -> AgentEvent:
        event = AgentEvent.model_validate(  # validates agent/type names before storing
            {"seq": 0, "ts": store.now_iso(), "elapsed_s": elapsed_s or 0.0, "run_id": self.run_id,
             "agent": agent, "type": type, "message": message, "tag": tag, "data": data or {}})
        stored = store.append_event(self.run_id, agent=event.agent, type=event.type,
                                    message=event.message, tag=event.tag, data=event.data,
                                    elapsed_s=elapsed_s)
        if is_final(stored):
            store.set_run_status(self.run_id, "done" if stored["type"] == "done" else "error")
        _notify(self.run_id)
        return AgentEvent.model_validate(stored)

    # Small helpers for the common shapes in shared/contract.md -------------------------

    def plan(self, steps: list[str], message: str | None = None) -> AgentEvent:
        return self("Partner", "plan", message or f"Made a {len(steps)}-step plan.", tag="Plan",
                    data={"steps": steps})

    def step(self, agent: str, message: str, **data: Any) -> AgentEvent:
        return self(agent, "step", message, data=data)

    def tool(self, agent: str, tool: str, message: str, **data: Any) -> AgentEvent:
        return self(agent, "tool", message, data={"tool": tool, **data})

    def handoff(self, frm: str, to: str | list[str], message: str, payload_summary: str,
                **data: Any) -> AgentEvent:
        return self(frm, "handoff", message, tag="Hand-off",
                    data={"from": frm, "to": to, "payload_summary": payload_summary, **data})

    def finding(self, agent: str, message: str, tag: str | None = None, **data: Any) -> AgentEvent:
        return self(agent, "finding", message, tag=tag, data=data)

    def warning(self, agent: str, message: str, tag: str | None = "Retrying", **data: Any) -> AgentEvent:
        return self(agent, "warning", message, tag=tag, data=data)

    def recovered(self, agent: str, message: str, fallback: str, **data: Any) -> AgentEvent:
        return self(agent, "recovered", message, tag="Recovered", data={"fallback": fallback, **data})

    def done(self, agent: str, message: str, run_done: bool = False, **data: Any) -> AgentEvent:
        if run_done:
            data["run_done"] = True
        return self(agent, "done", message, tag="Done" if run_done else None, data=data)

    def error(self, agent: str, message: str, reason: str | None = None, **data: Any) -> AgentEvent:
        if reason:
            data["reason"] = reason
        return self(agent, "error", message, data=data)

    def set_state(self, **fields: Any) -> None:
        """Save run-level fields shown on the Research page: partner_summary, since_last_run."""
        store.update_run_state(self.run_id, **fields)


# ---------------------------------------------------------------------------
# Starting runs
# ---------------------------------------------------------------------------


def new_run_id(fund_id: str) -> str:
    return f"run_{fund_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"


def default_task(fund_name: str) -> str:
    return f"Find {fund_name}’s next 10 deals and write a memo for the best one"


def start_run(fund_url: str, task: str | None = None, speed: float | None = None,
              since_last_run: str | None = None) -> dict:
    """Create a run row and start it in the background. Returns the run row."""
    fund_id = data.fund_id_from_url(fund_url)
    fund = data.get_fund(fund_id, fund_url)
    mode = "live" if config.live_ready() else "replay"
    previous = store.latest_run(fund_id)
    run = store.create_run(new_run_id(fund_id), fund_id, fund_url, task or default_task(fund.name),
                           mode, state={"speed": speed or config.replay_speed(),
                                        "since_last_run": since_last_run,
                                        "previous_run_id": previous["id"] if previous else None})
    _spawn(run["id"], _run_main(run["id"]))
    return run


def _spawn(run_id: str, coro) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _tasks[run_id] = task
    task.add_done_callback(lambda _t: _tasks.pop(run_id, None))


NO_KEY_MESSAGE = ("Live mode needs an Anthropic API key. Add ANTHROPIC_API_KEY to the .env file, or set "
                  "DEMO_MODE=replay to watch a recorded run.")


async def _run_main(run_id: str) -> None:
    run = store.get_run(run_id)
    assert run is not None
    emit = Emitter(run_id)
    try:
        if run["mode"] == "live":
            from .agents.runner import LLMUnavailable, run_live
            try:
                await run_live(run_id, run["fund_url"], emit, fund_id=run["fund_id"], task=run["task"])
            except NotImplementedError:
                emit.warning("Partner", "The live analyst team isn't switched on yet. "
                             "Showing a recorded run instead.", tag="Retrying")
                emit.recovered("Partner", "Switched to a recorded run so you can still see the work.",
                               fallback="recorded run")
                await replay(run_id)
                return
            except LLMUnavailable as exc:
                if exc.reason == "no_connection" and not _has_results(run_id):
                    emit.warning("Partner", "Couldn't reach Claude, so the live team can't work right now.",
                                 tag="Retrying")
                    emit.recovered("Partner", "Switched to a recorded run so you can still see the work.",
                                   fallback="recorded run")
                    store.update_run_state(run_id, replay_pos=0)
                    await replay(run_id)
                    return
                message = NO_KEY_MESSAGE if exc.reason == "no_api_key" else f"{exc} Earlier results are safe."
                emit.error("Partner", message, reason=exc.reason)
                return
            if store.get_run(run_id)["status"] == "running":  # type: ignore[index]
                emit.done("Partner", "Done. Every claim has a source, and a person makes the call.",
                          run_done=True)
            record(run_id)
        else:
            if config.demo_mode() == "live" and not config.llm_key():
                emit.error("Partner", NO_KEY_MESSAGE, reason="no_api_key")
                return
            await replay(run_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # the run must end with a plain-English error, never hang
        log.exception("run %s failed", run_id)
        emit.error("Partner", "Something went wrong and the run stopped. Your earlier results are safe.",
                   reason=type(exc).__name__)


def _has_results(run_id: str) -> bool:
    """True once a live run checkpointed any stage."""
    run = store.get_run(run_id)
    if not run:
        return False
    return any(k.startswith(f"ckpt:{run_id}:") and not k.endswith(":plan")
               for k in store.list_memory(run["fund_id"], f"ckpt:{run_id}:"))


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def recording_for(fund_id: str) -> tuple[list[dict], str]:
    """(events, source fund id). data/cache/replay/<fund>.jsonl, data/cache/<fund>.jsonl,
    else the demo recording (frontend/src/mocks/research_events.json)."""
    for path in (config.REPLAY_DIR / f"{fund_id}.jsonl", config.CACHE_DIR / f"{fund_id}.jsonl"):
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            return [json.loads(line) for line in lines if line.strip()], fund_id
    return [dict(e) for e in data.mock_events()], data.demo_fund_id()


async def replay(run_id: str) -> None:
    """Stream a recorded event log into the run with its original gaps (divided by `speed`).

    Resumable: the position is checkpointed in runs.state.replay_pos.
    """
    run = store.get_run(run_id)
    assert run is not None
    emit = Emitter(run_id)
    events, source = recording_for(run["fund_id"])
    state = run["state"]
    speed = float(state.get("speed") or 1.0)
    pos = int(state.get("replay_pos") or 0)

    if pos == 0 and source != run["fund_id"]:
        fund = data.get_fund(source)
        emit("Partner", "step", f"There is no recording for this fund yet, so this replays a "
             f"recorded {fund.name} run.", elapsed_s=0.0)

    since = state.get("since_last_run")
    prev_elapsed = float(events[pos - 1]["elapsed_s"]) if pos else 0.0
    for i in range(pos, len(events)):
        ev = events[i]
        gap = max(0.0, float(ev["elapsed_s"]) - prev_elapsed) / speed
        if gap:
            await asyncio.sleep(gap)
        prev_elapsed = float(ev["elapsed_s"])
        message = ev["message"]
        if since and ev["agent"] == "Partner" and ev["type"] == "done" and ev["data"].get("run_done"):
            message = f"{since}. {message}"
        emit(ev["agent"], ev["type"], message, tag=ev.get("tag"), data=ev.get("data") or {},
             elapsed_s=float(ev["elapsed_s"]))
        store.update_run_state(run_id, replay_pos=i + 1)

    if store.get_run(run_id)["status"] == "running":  # recording had no final event
        emit.done("Partner", "Done.", run_done=True)


def live_dir() -> Path:
    """Where live runs are recorded: data/cache/replay/live/. Replay never reads from here."""
    return config.REPLAY_DIR / "live"


def recording_path(run: dict) -> Path:
    return live_dir() / f"{run['fund_id']}-{run['id']}.jsonl"


def record(run_id: str) -> Optional[Path]:
    """Save a finished live run as data/cache/replay/live/<fund>-<run_id>.jsonl.

    It never overwrites the demo recording (data/cache/replay/<fund>.jsonl). To make a good rehearsal the
    new backup, promote it on purpose: `python scripts/promote_recording.py <file or run id>`.
    Returns the path written, or None.
    """
    run = store.get_run(run_id)
    if not run or run["status"] != "done":
        return None
    path = recording_path(run)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ev in store.get_events(run_id):
            f.write(json.dumps(ev, ensure_ascii=False) + chr(10))
    return path


def list_live_recordings(fund_id: str | None = None) -> list[Path]:
    """Live recordings, newest first."""
    d = live_dir()
    if not d.exists():
        return []
    files = [f for f in d.glob("*.jsonl") if fund_id is None or f.name.startswith(f"{fund_id}-run_")]
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


def promote_recording(source: str, fund_id: str | None = None) -> Path:
    """Copy a live recording to data/cache/replay/<fund>.jsonl (the one replay uses).

    `source` is a file path, a run id, or a fund id (its newest live recording). The current recording, if
    any, is kept as <fund>.jsonl.bak. Returns the new replay path. Raises ValueError (plain English).
    """
    src = Path(source)
    if not src.exists():
        candidates = ([f for f in list_live_recordings() if f.stem.endswith(f"-{source}")]
                      or list_live_recordings(source))
        if not candidates:
            raise ValueError(f"No live recording found for {source!r}.")
        src = candidates[0]
    lines = [line for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"{src.name} is empty.")
    events = [AgentEvent.model_validate(json.loads(line)) for line in lines]  # refuse broken files
    if not is_final(events[-1].model_dump()):
        raise ValueError(f"{src.name} doesn't end with the run's final event, so it isn't a finished run.")
    fund = fund_id or (src.stem.split("-run_")[0] if "-run_" in src.stem else None)
    if not fund:
        raise ValueError("Couldn't tell which fund this recording is for. Pass the fund id.")
    dest = config.REPLAY_DIR / f"{fund}.jsonl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.with_suffix(".jsonl.bak").write_bytes(dest.read_bytes())
    dest.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    return dest


def seed_demo_run() -> None:
    """Make `run_demo_localglobe` exist (finished) so GET /api/runs/run_demo_localglobe/... works."""
    if store.get_run(config.DEMO_RUN_ID):
        return
    rec = data.mock_events()
    mock_run = data.mock("run")
    store.create_run(config.DEMO_RUN_ID, mock_run.fund.id, mock_run.fund.url, mock_run.task, "replay",
                     started_at=mock_run.started_at,
                     state={"partner_summary": mock_run.partner_summary,
                            "since_last_run": mock_run.since_last_run, "replay_pos": len(rec)})
    for ev in rec:
        store.append_event(config.DEMO_RUN_ID, agent=ev["agent"], type=ev["type"],
                           message=ev["message"], tag=ev.get("tag"), data=ev.get("data") or {},
                           ts=ev["ts"], elapsed_s=ev["elapsed_s"])
    store.set_run_status(config.DEMO_RUN_ID, "done")


def resume_unfinished() -> None:
    """On startup: continue cut-off replays; resume live runs from their checkpoints (needs the key)."""
    for run in store.list_runs(status="running", limit=200):
        if run["id"] in _tasks:
            continue
        emit = Emitter(run["id"])
        if run["mode"] == "replay":
            emit.recovered("Partner", "The server restarted. Picking up where the run left off.",
                           fallback="checkpoint")
            _spawn(run["id"], replay(run["id"]))
        elif config.live_ready():
            # Live runs checkpoint every stage (app.agents.context.RunContext.stage): finished stages are
            # loaded, not redone.
            store.update_run_state(run["id"], resumed=True)
            emit.recovered("Partner", "The server restarted. Picking up from the last saved step.",
                           fallback="checkpoint")
            _spawn(run["id"], _run_main(run["id"]))
        else:
            emit.error("Partner", "The server restarted during this run. Start it again to continue.",
                       reason="restart")


async def stop_all() -> None:
    for task in list(_tasks.values()):
        task.cancel()
    if _tasks:
        await asyncio.gather(*_tasks.values(), return_exceptions=True)


# ---------------------------------------------------------------------------
# RunState (derived from the event log)
# ---------------------------------------------------------------------------


def plan_and_agents(events: list[dict], run_status: str) -> tuple[list[PlanStep], list[AgentStatus]]:
    steps: list[str] = list(DEFAULT_PLAN)
    status: dict[int, str] = {}
    agents: dict[str, str] = {a: "waiting" for a in AGENTS}
    for ev in events:
        d = ev["data"]
        if ev["type"] == "plan" and isinstance(d.get("steps"), list):
            steps = [str(s) for s in d["steps"]]
        if isinstance(d.get("plan_step"), int) and d.get("plan_status") in ("working", "done"):
            status[d["plan_step"]] = d["plan_status"]
        a = ev["agent"]
        if ev["type"] == "error":
            agents[a] = "error"
        elif ev["type"] == "done" and (a != "Partner" or d.get("run_done")):
            agents[a] = "done"
        elif agents[a] == "waiting":
            agents[a] = "working"
    if run_status == "done":  # a finished run has no agent still working (not every agent sends `done`)
        agents = {a: ("done" if s == "working" else s) for a, s in agents.items()}
    plan = []
    for i, label in enumerate(steps, start=1):
        s = "done" if run_status == "done" else status.get(i, "waiting")
        plan.append(PlanStep(label=label, status=s))  # type: ignore[arg-type]
    return plan, [AgentStatus(name=n, status=s) for n, s in agents.items()]  # type: ignore[arg-type]


def plan_progress(run_id: str | None) -> tuple[int, int]:
    run = store.get_run(run_id) if run_id else None
    if not run:
        return 0, len(DEFAULT_PLAN)
    plan, _ = plan_and_agents(store.get_events(run_id), run["status"])  # type: ignore[arg-type]
    return sum(1 for p in plan if p.status == "done"), len(plan)


def run_state(run_id: str) -> Optional[RunState]:
    run = store.get_run(run_id)
    if run is None:
        return None
    events = store.get_events(run_id)
    plan, agents = plan_and_agents(events, run["status"])
    st = run["state"]
    shortlist, memo_ids = [], []
    seen: set[str] = set()
    for ev in events:
        d = ev["data"]
        cid = d.get("company_id")
        if ev["type"] == "finding" and ev["tag"] == "New match" and cid and cid not in seen:
            item = data.deal_item(run["fund_id"], cid)
            if item:
                shortlist.append(item)
                seen.add(cid)
        mid = d.get("memo_id")
        if mid and mid not in memo_ids and data.memo(run["fund_id"], mid):
            memo_ids.append(mid)
    return RunState(
        run_id=run_id,
        fund=data.get_fund(run["fund_id"], run["fund_url"]),
        status=run["status"],
        task=run["task"],
        started_at=run["started_at"],
        elapsed_s=float(events[-1]["elapsed_s"]) if events else 0.0,
        plan=plan,
        agents=agents,
        partner_summary=st.get("partner_summary") or _latest_partner_line(events),
        since_last_run=st.get("since_last_run"),
        shortlist=shortlist,
        memo_ids=memo_ids,
    )


def _latest_partner_line(events: list[dict]) -> Optional[str]:
    for ev in reversed(events):
        if ev["agent"] == "Partner" and ev["type"] in ("step", "done", "plan"):
            return ev["message"]
    return None


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------


def _asking(run_id: str) -> bool:
    """True while the team answers a question on this run (the stream stays open past the run's end)."""
    run = store.get_run(run_id)
    return bool(run and _asking_state(run))


def _asking_state(run: dict) -> bool:
    since = (run["state"] or {}).get("asking")  # ISO time the question started; stale after 5 min (e.g. a restart)
    if not since:
        return False
    try:
        started = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
        return (datetime.now(started.tzinfo) - started) < timedelta(minutes=5)
    except ValueError:
        return False


def sse_format(event: dict) -> str:
    payload = AgentEvent.model_validate(event).model_dump_json()
    return f"id: {event['seq']}\nevent: agent\ndata: {payload}\n\n"


async def event_stream(run_id: str, last_event_id: int = 0,
                       speed: float | None = None) -> AsyncIterator[str]:
    """Replays past events (seq > last_event_id), then streams new ones until the run ends.

    `speed`: if set, past events are paced by their recorded gaps / speed instead of sent at once.
    """
    last = last_event_id
    prev_elapsed: Optional[float] = None
    yield "retry: 3000\n\n"
    while True:
        signal = _signal(run_id)  # take the signal BEFORE reading, so no event is missed
        for ev in store.get_events(run_id, after_seq=last):
            if speed and prev_elapsed is not None:
                await asyncio.sleep(max(0.0, ev["elapsed_s"] - prev_elapsed) / speed)
            prev_elapsed = ev["elapsed_s"]
            last = ev["seq"]
            yield sse_format(ev)
            if is_final(ev) and not _asking(run_id):
                return
        run = store.get_run(run_id)
        if run is None or (run["status"] != "running" and not _asking_state(run)):
            return
        try:
            await asyncio.wait_for(signal.wait(), timeout=PING_EVERY_S)
        except asyncio.TimeoutError:
            yield ": ping\n\n"


# ---------------------------------------------------------------------------
# Watch mode helpers
# ---------------------------------------------------------------------------


def next_morning(hour: int = 7) -> datetime:
    now = datetime.now().astimezone()
    nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return nxt


def next_run_label(iso: str | None) -> str:
    if not iso:
        return "Not scheduled"
    when = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
    today = datetime.now().astimezone().date()
    time = f"{when.hour}:{when.minute:02d}"
    if when.date() == today:
        return f"{time} today"
    if when.date() == today + timedelta(days=1):
        return f"{time} tomorrow"
    return f"{when.strftime('%a')} {time}"


async def watch_loop(check_every_s: float = 60.0) -> None:
    """In-process scheduler: start a re-run for each watched fund when its time comes."""
    while True:
        await asyncio.sleep(check_every_s)
        try:
            now = datetime.now().astimezone()
            for w in store.list_watches():
                if not w["next_run_at"]:
                    continue
                due = datetime.fromisoformat(w["next_run_at"].replace("Z", "+00:00"))
                if due <= now:
                    if now - due > timedelta(minutes=30):
                        # Missed while the server was off: don't fire a surprise run at startup, just reschedule.
                        store.set_watch(w["fund_id"], True, next_morning().isoformat())
                        continue
                    run = store.latest_run(w["fund_id"])
                    url = run["fund_url"] if run else data.get_fund(w["fund_id"]).url
                    start_run(url, since_last_run=None)
                    store.set_watch(w["fund_id"], True, next_morning().isoformat())
        except Exception:  # never let the scheduler die
            log.exception("watch loop tick failed")
