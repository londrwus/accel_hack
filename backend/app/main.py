"""Bellwether API. Endpoints follow shared/contract.md.

Run: python -m uv run uvicorn app.main:app --port 8000   (from backend/)
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import company_detail, config, data, logo_fill, modal_client, runs, store, map_views
from .tools import logos
from .models import (
    AskCreated,
    AskRequest,
    QuestionItem,
    QuestionsResponse,
    Backtest,
    Company,
    CompanyDetail,
    DealsResponse,
    Feedback,
    FundResponse,
    FundsResponse,
    MapResponse,
    Memo,
    MemosResponse,
    Ok,
    PortfolioResponse,
    RunCreate,
    RunCreated,
    RunState,
    UniverseResponse,
    WatchRequest,
    WatchResponse,
    WatchStatus,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bellwether")


def _preload_live() -> None:
    try:
        import app.agents.partner  # noqa: F401  (imports every agent)
        from .tools import tls
        tls.context()  # build the shared TLS context once (~2s)
        from .tools import dataset
        dataset.rows()
    except Exception:
        log.exception("preloading the live agents failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    store.init_db()
    runs.bind_loop(asyncio.get_running_loop())
    runs.seed_demo_run()
    runs.resume_unfinished()
    logo_fill.prewarm()
    if config.live_ready():  # load the agent code and the dataset now, not during the first live run (~8s)
        asyncio.get_running_loop().run_in_executor(None, _preload_live)
    watcher = asyncio.create_task(runs.watch_loop())
    log.info("Bellwether API ready. DEMO_MODE=%s, live agents %s.", config.demo_mode(),
             "on" if config.live_ready() else "off")
    yield
    watcher.cancel()
    await runs.stop_all()


app = FastAPI(title="Bellwether API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                   allow_origin_regex=config.CORS_ORIGIN_REGEX or None, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------------------
# Errors: always {"error": "Plain-English reason"}
# ---------------------------------------------------------------------------


@app.exception_handler(StarletteHTTPException)
async def _http_error(_req: Request, exc: StarletteHTTPException):
    msg = exc.detail if isinstance(exc.detail, str) else "Something went wrong."
    if exc.status_code == 404 and msg == "Not Found":
        msg = "There's nothing at this address."
    return JSONResponse({"error": msg}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def _validation_error(_req: Request, exc: RequestValidationError):
    fields = ", ".join(str(e["loc"][-1]) for e in exc.errors()[:3])
    return JSONResponse({"error": f"Some of the request is missing or not valid ({fields})."},
                        status_code=422)


@app.exception_handler(data.NoData)
async def _no_data(_req: Request, exc: data.NoData):
    return JSONResponse({"error": str(exc)}, status_code=404)


@app.exception_handler(Exception)
async def _server_error(_req: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse({"error": "Something went wrong on our side. Please try again."},
                        status_code=500)


def _fund(fund_id: Optional[str]) -> str:
    return fund_id or config.default_fund_id()


def _run_or_404(run_id: str) -> dict:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(404, "We couldn't find that run.")
    return run


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health() -> dict:
    """Not in shared/contract.md. modal: "deployed" | "fallback"; anthropic: "key present" | "no key"."""
    has_key = bool(config.anthropic_key())
    out = {"ok": True, "demo_mode": config.demo_mode(), "live_agents": config.live_ready(),
           "anthropic": "key present" if has_key else "no key", "anthropic_key": has_key,
           "companies_csv": data.csv_available()}
    out.update(await modal_client.health())
    return out


# ---------------------------------------------------------------------------
# Page endpoints
# ---------------------------------------------------------------------------


def _watch_status(fund_id: str) -> WatchStatus:
    row = store.get_watch(fund_id)
    latest = store.latest_run(fund_id)
    if row is None:
        mock = data.mock_watch(fund_id)
        if mock is not None and (latest is None or latest["id"] == config.DEMO_RUN_ID):
            return mock
    done, total = runs.plan_progress(latest["id"] if latest else None)
    enabled = bool(row and row["enabled"])
    next_at = row["next_run_at"] if row and enabled else None
    return WatchStatus(enabled=enabled, next_run_at=next_at, next_run_label=runs.next_run_label(next_at),
                       progress_done=done, progress_total=total)


@app.get("/api/funds", response_model=FundsResponse)
def get_funds() -> FundsResponse:
    """Every fund you can switch to: the demo fund, funds you cover, funds with runs or results."""
    return FundsResponse(items=data.list_funds())


@app.get("/api/fund", response_model=FundResponse)
def get_fund(fund_id: Optional[str] = None) -> FundResponse:
    fid = _fund(fund_id)
    try:
        new_deals = data.deals(fid).counts.new
    except data.NoData:
        new_deals = 0
    latest = store.latest_run(fid)
    return logo_fill.fill(FundResponse(fund=data.get_fund(fid), covered_funds=data.covered_funds(fid),
                                       watch=_watch_status(fid), new_deals=new_deals,
                                       latest_run_id=latest["id"] if latest else None))


@app.get("/api/deals", response_model=DealsResponse)
def get_deals(fund_id: Optional[str] = None,
              status: Optional[str] = Query(None, pattern="^(new|under_review|passed)$"),
              sector: Optional[str] = None, sort: Optional[str] = "fit") -> DealsResponse:
    return logo_fill.fill(data.deals(_fund(fund_id), status=status, sector=sector, sort=sort))


@app.get("/api/portfolio", response_model=PortfolioResponse)
def get_portfolio(fund_id: Optional[str] = None) -> PortfolioResponse:
    return logo_fill.fill(data.portfolio(_fund(fund_id)))


@app.get("/api/map", response_model=MapResponse)
async def get_map(fund_id: Optional[str] = None, fund: Optional[str] = None,
                  view: str = Query("portfolio", pattern="^(portfolio|theme|new|competition)$"),
                  center: Optional[str] = None, sector: Optional[str] = None, country: Optional[str] = None,
                  stage: Optional[str] = None, limit: int = Query(10, ge=1, le=50)) -> MapResponse:
    return logo_fill.fill(await map_views.build(_fund(fund_id or fund), view=view, center=center or None,
                                                sector=sector or None, country=country or None,
                                                stage=stage or None, limit=limit))


@app.get("/api/memos", response_model=MemosResponse)
def get_memos(fund_id: Optional[str] = None) -> MemosResponse:
    return logo_fill.fill(data.memos(_fund(fund_id)))


@app.get("/api/memos/{memo_id}", response_model=Memo)
def get_memo(memo_id: str, fund_id: Optional[str] = None) -> Memo:
    memo = data.memo(_fund(fund_id), memo_id)
    if memo is None:
        raise HTTPException(404, "There's no memo for this company yet.")
    return logo_fill.fill(memo)


@app.get("/api/universe", response_model=UniverseResponse)
async def get_universe(q: Optional[str] = None, page: int = Query(1, ge=1),
                       page_size: int = Query(50, ge=1, le=200), sector: Optional[str] = None,
                       country: Optional[str] = None, stage: Optional[str] = None,
                       founded: Optional[int] = None, fund_id: Optional[str] = None,
                       sort: Optional[str] = Query(None, pattern="^(fit|name|founded|funding)$")) -> UniverseResponse:
    ranked = None
    if q and q.strip() and data.csv_available():  # search by meaning when the model is up; words otherwise
        ranked = await modal_client.search_ids(q, k=min(200, max(100, page * page_size)))
    return logo_fill.fill(data.universe(_fund(fund_id), q=q, page=page, page_size=page_size, sector=sector,
                                        country=country, stage=stage, founded=founded, ranked_ids=ranked,
                                        sort=sort))


@app.get("/api/backtest", response_model=Backtest)
async def get_backtest(fund_id: Optional[str] = None) -> Backtest:
    """The saved file, else "not enough history" when the dataset has too few dated deals, else a Modal
    backtest (started once, picked up by a later request if it runs long), else 404. Never mock numbers."""
    r = await modal_client.backtest(_fund(fund_id))
    if r.value is None:
        raise HTTPException(404, "No backtest yet for this fund")
    return Backtest.model_validate(r.value)


@app.get("/api/companies/{company_id}", response_model=Company)
def get_company(company_id: str, fund_id: Optional[str] = None) -> Company:
    c = data.company(company_id, _fund(fund_id))
    if c is None:
        raise HTTPException(404, "We couldn't find that company.")
    return logo_fill.fill(c)


@app.get("/api/companies/{company_id}/detail", response_model=CompanyDetail)
async def get_company_detail(company_id: str, fund_id: Optional[str] = None) -> CompanyDetail:
    """Everything about one company and how it scored for this fund (the /companies/:id page)."""
    d = await company_detail.detail(company_id, _fund(fund_id))
    if d is None:
        raise HTTPException(404, "We couldn't find that company.")
    return logo_fill.fill(d)


_IMG_HEADERS = {"Cache-Control": "public, max-age=86400"}


@app.get("/api/logos/dataset/{file}")
def logo_dataset(file: str) -> FileResponse:
    path = logos.dataset_file(file)
    if path is None:
        raise HTTPException(404, "No logo here.")
    return FileResponse(path, headers=_IMG_HEADERS)


@app.get("/api/logos/site/{file}")
def logo_site(file: str) -> FileResponse:
    path = logos.site_file(file)
    if path is None:
        raise HTTPException(404, "No logo here.")
    media = "image/svg+xml" if file.endswith(".svg") else None
    return FileResponse(path, media_type=media, headers=_IMG_HEADERS)


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@app.post("/api/runs", response_model=RunCreated, status_code=201)
async def create_run(body: RunCreate, speed: Optional[float] = Query(None, gt=0, le=100)) -> RunCreated:
    if not body.fund_url.strip():
        raise HTTPException(422, "Please paste a fund website address.")
    if not body.force:  # this fund already has finished results: show them instead of re-running
        done = store.list_runs(fund_id=data.fund_id_from_url(body.fund_url), status="done", limit=1)
        if done:
            return RunCreated(run_id=done[0]["id"], fund_id=done[0]["fund_id"], reused=True)
    run = runs.start_run(body.fund_url, body.task, speed=speed)
    return RunCreated(run_id=run["id"], fund_id=run["fund_id"])


@app.get("/api/runs/{run_id}", response_model=RunState)
def get_run(run_id: str) -> RunState:
    _run_or_404(run_id)
    return logo_fill.fill(runs.run_state(run_id))  # type: ignore[return-value]


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request,
                     last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
                     after: Optional[int] = Query(None, ge=0, alias="last_event_id"),
                     speed: Optional[float] = Query(None, gt=0, le=100)) -> StreamingResponse:
    _run_or_404(run_id)
    try:
        start = int(last_event_id) if last_event_id else (after or 0)
    except ValueError:
        start = 0

    async def body():
        async for chunk in runs.event_stream(run_id, start, speed):
            if await request.is_disconnected():
                return
            yield chunk

    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


@app.get("/api/runs/{run_id}/memo/{company_id}", response_model=Memo)
async def run_memo(run_id: str, company_id: str) -> Memo:
    run = _run_or_404(run_id)
    memo = data.memo(run["fund_id"], company_id)
    if memo is None and config.live_ready():
        from .agents.runner import write_memo
        memo = await write_memo(run_id, run["fund_id"], company_id, runs.Emitter(run_id))
        if memo is not None:
            data.save_memo(run["fund_id"], memo)
    if memo is None:
        raise HTTPException(404, "There's no memo for this company yet.")
    return memo


_WEIGHT_STEP = {"meeting": 0.1, "dig_deeper": 0.0, "pass": -0.1}


@app.post("/api/runs/{run_id}/feedback", response_model=Ok)
def run_feedback(run_id: str, body: Feedback) -> Ok:
    """Records a human decision. It never contacts anyone: 'Move to first meeting' only records it."""
    run = _run_or_404(run_id)
    fund_id = run["fund_id"]
    store.add_feedback(run_id, fund_id, body.company_id, body.verdict, body.note)
    company = data.company(body.company_id, fund_id)
    if company is not None:  # nudge the thesis weights used by the next run
        weights = store.get_memory(fund_id, "thesis_weights", {}) or {}
        key = f"sector:{company.sector}"
        weights[key] = round(weights.get(key, 0.0) + _WEIGHT_STEP[body.verdict], 2)
        store.set_memory(fund_id, "thesis_weights", weights)
    return Ok()


# ---------------------------------------------------------------------------
# Ask the team (chat on /research)
# ---------------------------------------------------------------------------


def _question_item(q: dict) -> QuestionItem:
    companies = [c for c in (data.company(cid, q["fund_id"]) for cid in q["company_ids"]) if c is not None]
    return QuestionItem(**q, companies=companies)


def _ask(run_id: str, question: str) -> AskCreated:
    from .agents import ask

    if not question.strip():
        raise HTTPException(422, "Please type a question.")
    row = ask.start_question(run_id, question)
    return AskCreated(question_id=row["id"], run_id=run_id)


@app.post("/api/runs/{run_id}/ask", response_model=AskCreated, status_code=202)
async def ask_run(run_id: str, body: AskRequest) -> AskCreated:
    """Routes the question to the team; every step streams into the run feed (tag "Question")."""
    _run_or_404(run_id)
    return _ask(run_id, body.question)


@app.post("/api/funds/{fund_id}/ask", response_model=AskCreated, status_code=202)
async def ask_fund(fund_id: str, body: AskRequest) -> AskCreated:
    """Same, for a fund: uses its latest run, or opens a small run to hold the Q&A when it has none."""
    run = store.latest_run(fund_id)
    if run is None:
        fund = data.get_fund(fund_id)
        run = store.create_run(runs.new_run_id(fund_id), fund_id, fund.url, f"Questions about {fund.name}",
                               "live", status="done")
    return _ask(run["id"], body.question)


@app.get("/api/funds/{fund_id}/questions", response_model=QuestionsResponse)
def fund_questions(fund_id: str) -> QuestionsResponse:
    return QuestionsResponse(items=[_question_item(q) for q in store.list_questions(fund_id)])


@app.get("/api/questions/{question_id}", response_model=QuestionItem)
def get_question(question_id: str) -> QuestionItem:
    q = store.get_question(question_id)
    if q is None:
        raise HTTPException(404, "There's no such question.")
    return _question_item(q)


@app.post("/api/funds/{fund_id}/watch", response_model=WatchResponse)
async def watch_fund(fund_id: str, body: WatchRequest) -> WatchResponse:
    next_at = runs.next_morning().isoformat() if body.enabled else None
    store.set_watch(fund_id, body.enabled, next_at)
    run_id = None
    if body.simulate_next_run:
        latest = store.latest_run(fund_id)
        url = latest["fund_url"] if latest else data.get_fund(fund_id).url
        since = None
        if fund_id == data.demo_fund_id() and not config.live_ready():
            # Replay placeholder copy from the design. Live runs compute it (app.agents.watch).
            since = data.mock("run").since_last_run
        run_id = runs.start_run(url, since_last_run=since)["id"]
    return WatchResponse(watch=_watch_status(fund_id), run_id=run_id)


_JOBS: set = set()  # keeps background enrich jobs alive


@app.post("/api/funds/{fund_id}/enrich")
async def enrich_fund(fund_id: str, wait: bool = False, force: bool = False) -> dict:
    """Fill in profiles for this fund's portfolio and shortlist companies that the dataset lacks.
    Runs in the background unless ?wait=true. Progress goes to the server log."""
    from .agents import enricher
    from .agents.context import RunContext
    from .agents.runner import _llm_factory, _require_key
    _require_key()
    companies = []
    try:
        companies += [it.company for col in data.portfolio(fund_id).columns for it in col.items + col.rest]
    except data.NoData:
        pass
    try:
        companies += [i.company for i in data.deals(fund_id).items]
    except data.NoData:
        pass
    if not companies:
        raise HTTPException(404, "Nothing for this fund yet. Start a run first.")
    fund = data.get_fund(fund_id)
    ctx = RunContext(f"enrich_{fund_id}", fund_id, fund.url, "", enricher.LogEmitter(), _llm_factory())
    ctx.fund_name = fund.name
    todo = [c for c in companies if enricher.needs_enrichment(c)]
    job = enricher.run(ctx, fund.url, companies, force=force)
    if wait:
        return {"fund_id": fund_id, **(await job)}
    task = asyncio.ensure_future(job)
    _JOBS.add(task)
    task.add_done_callback(_JOBS.discard)
    return {"fund_id": fund_id, "started": True, "candidates": len({c.id for c in todo})}


@app.delete("/api/funds/{fund_id}/data", response_model=Ok)
async def delete_fund_data(fund_id: str) -> Ok:
    """'Delete fund data' (docs/RESPONSIBLE_AI.md). Not in shared/contract.md yet."""
    for run in store.list_runs(fund_id=fund_id, limit=1000):
        if run["status"] == "running":
            raise HTTPException(409, "A run for this fund is still going. Try again when it finishes.")
    store.delete_fund_data(fund_id)
    return Ok()
