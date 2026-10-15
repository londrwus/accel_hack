"""Bellwether API. Endpoints follow shared/contract.md.

Run: python -m uv run uvicorn app.main:app --port 8000   (from backend/)
"""

from __future__ import annotations

import asyncio
import os
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import company_detail, config, data, logo_fill, modal_client, page_cache, runs, store, map_views
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
    SimilarResponse,
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


WARM_FUNDS = ("accel", "localglobe")


async def _warm(fid: str) -> None:
    """Render every page of a fund into page_cache (the demo funds are warm before anyone opens them)."""
    async def step(name, fn):
        try:
            r = fn()
            if asyncio.iscoroutine(r):
                await r
        except Exception as e:  # a page with no data yet is fine
            log.debug("warm %s %s: %s", fid, name, e)

    await step("funds", lambda: asyncio.to_thread(get_funds))
    await step("fund", lambda: asyncio.to_thread(get_fund, fid))
    await step("deals", lambda: asyncio.to_thread(get_deals, fid, None, None, "fit"))
    for st in ("new", "under_review", "passed"):
        await step("deals", lambda st=st: asyncio.to_thread(get_deals, fid, st, None, "fit"))
    await step("portfolio", lambda: asyncio.to_thread(get_portfolio, fid))
    await step("memos", lambda: asyncio.to_thread(get_memos, fid))
    for view in ("portfolio", "theme", "new", "competition"):
        await step("map", lambda view=view: get_map(fid, None, view, None, None, None, None, 10))
    await step("universe", lambda: get_universe(None, 1, 50, None, None, None, None, fid, None))
    await step("backtest", lambda: get_backtest(fid))
    ids: list[str] = []
    try:
        ids += [m.id for m in data.memos(fid).items]
        for mid in ids:
            await step("memo", lambda mid=mid: asyncio.to_thread(get_memo, mid, fid))
        ids += [i.company.id for i in data.deals(fid).items]
        ids += [i.company.id for col in data.portfolio(fid).columns for i in col.items]
    except Exception:
        pass
    for cid in dict.fromkeys(ids):
        await step("detail", lambda cid=cid: get_company_detail(cid, fid))


async def _warm_loop() -> None:
    """Warm the demo funds at startup, and again whenever a write has cleared the cache."""
    await asyncio.to_thread(lambda: (data.csv_available() and data._csv_rows(), company_detail._csv_index()))
    while True:
        for fid in WARM_FUNDS:
            if page_cache.get(("portfolio", fid)) is None:
                t = asyncio.get_running_loop().time()
                await _warm(fid)
                log.info("warmed %s pages in %.1fs", fid, asyncio.get_running_loop().time() - t)
        await asyncio.sleep(20)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    store.init_db()
    runs.bind_loop(asyncio.get_running_loop())
    runs.seed_demo_run()
    runs.resume_unfinished()
    logo_fill.prewarm()
    if config.live_ready():  # load the agent code and the dataset now, not during the first live run (~8s)
        asyncio.get_running_loop().run_in_executor(None, _preload_live)
    warmer = asyncio.create_task(_warm_loop() if os.environ.get("PAGE_WARM", "1") != "0" else asyncio.sleep(0))
    watcher = asyncio.create_task(runs.watch_loop())
    log.info("Bellwether API ready. DEMO_MODE=%s, live agents %s.", config.demo_mode(),
             "on" if config.live_ready() else "off")
    yield
    watcher.cancel()
    warmer.cancel()
    await runs.stop_all()


app = FastAPI(title="Bellwether API", version="0.1.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)


def _json(body: bytes) -> Response:
    return Response(content=body, media_type="application/json")


def _cached(key, build) -> Response:
    return _json(page_cache.render(key, build))
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
    return _cached(("funds",), lambda: FundsResponse(items=data.list_funds()))


@app.get("/api/fund", response_model=FundResponse)
def get_fund(fund_id: Optional[str] = None) -> FundResponse:
    fid = _fund(fund_id)
    return _cached(("fund", fid), lambda: _fund_page(fid))


def _fund_page(fid: str) -> FundResponse:
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
    fid = _fund(fund_id)
    return _cached(("deals", fid, status, sector, sort),
                   lambda: logo_fill.fill(data.deals(fid, status=status, sector=sector, sort=sort)))


@app.get("/api/portfolio", response_model=PortfolioResponse)
def get_portfolio(fund_id: Optional[str] = None) -> PortfolioResponse:
    fid = _fund(fund_id)
    return _cached(("portfolio", fid), lambda: logo_fill.fill(data.portfolio(fid)))


@app.get("/api/map", response_model=MapResponse)
async def get_map(fund_id: Optional[str] = None, fund: Optional[str] = None,
                  view: str = Query("portfolio", pattern="^(portfolio|theme|new|competition)$"),
                  center: Optional[str] = None, sector: Optional[str] = None, country: Optional[str] = None,
                  stage: Optional[str] = None, limit: int = Query(10, ge=1, le=50)) -> MapResponse:
    fid = _fund(fund_id or fund)
    key = ("map", fid, view, center or None, sector or None, country or None, stage or None, limit)
    body = page_cache.get(key)
    if body is None:
        page = logo_fill.fill(await map_views.build(fid, view=view, center=center or None, sector=sector or None,
                                                    country=country or None, stage=stage or None, limit=limit))
        body = page_cache.put(key, page.model_dump_json().encode())
    return _json(body)


@app.get("/api/memos", response_model=MemosResponse)
def get_memos(fund_id: Optional[str] = None) -> MemosResponse:
    fid = _fund(fund_id)
    return _cached(("memos", fid), lambda: logo_fill.fill(data.memos(fid)))


@app.get("/api/memos/{memo_id}", response_model=Memo)
def get_memo(memo_id: str, fund_id: Optional[str] = None) -> Memo:
    fid = _fund(fund_id)

    def build() -> Memo:
        memo = data.memo(fid, memo_id)
        if memo is None:
            raise HTTPException(404, "There's no memo for this company yet.")
        return logo_fill.fill(memo)
    return _cached(("memo", fid, memo_id), build)


@app.get("/api/universe", response_model=UniverseResponse)
async def get_universe(q: Optional[str] = None, page: int = Query(1, ge=1),
                       page_size: int = Query(50, ge=1, le=200), sector: Optional[str] = None,
                       country: Optional[str] = None, stage: Optional[str] = None,
                       founded: Optional[int] = None, fund_id: Optional[str] = None,
                       sort: Optional[str] = Query(None, pattern="^(fit|name|founded|funding)$")) -> UniverseResponse:
    fid = _fund(fund_id)
    if not (q and q.strip()):
        return _cached(("universe", fid, page, page_size, sector, country, stage, founded, sort),
                       lambda: logo_fill.fill(data.universe(fid, q=q, page=page, page_size=page_size, sector=sector,
                                                            country=country, stage=stage, founded=founded,
                                                            sort=sort)))
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
    fid = _fund(fund_id)
    body = page_cache.get(("backtest", fid))
    if body is None:
        r = await modal_client.backtest(fid)
        if r.value is None:
            raise HTTPException(404, "No backtest yet for this fund")
        body = page_cache.put(("backtest", fid), Backtest.model_validate(r.value).model_dump_json().encode())
    return _json(body)


@app.get("/api/companies/{company_id}", response_model=Company)
def get_company(company_id: str, fund_id: Optional[str] = None) -> Company:
    c = data.company(company_id, _fund(fund_id))
    if c is None:
        raise HTTPException(404, "We couldn't find that company.")
    return logo_fill.fill(c)


@app.get("/api/companies/{company_id}/detail", response_model=CompanyDetail)
async def get_company_detail(company_id: str, fund_id: Optional[str] = None) -> CompanyDetail:
    """Everything about one company and how it scored for this fund (the /companies/:id page)."""
    fid = _fund(fund_id)
    key = ("detail", fid, company_id)
    body = page_cache.get(key)
    if body is None:
        d = await company_detail.detail(company_id, fid, with_similar=False)
        if d is None:
            raise HTTPException(404, "We couldn't find that company.")
        body = page_cache.put(key, logo_fill.fill(d).model_dump_json().encode())
    return _json(body)


@app.get("/api/companies/{company_id}/similar", response_model=SimilarResponse)
async def get_company_similar(company_id: str, fund_id: Optional[str] = None) -> Response:
    """Companies like this one (Modal model, ~3s cap, word-match fallback). Loaded after the page shows."""
    fid = _fund(fund_id)
    key = ("similar", fid, company_id)
    body = page_cache.get(key)
    if body is None:
        r = await company_detail.similar(company_id, fid)
        if r is None:
            raise HTTPException(404, "We couldn't find that company.")
        body = logo_fill.fill(r).model_dump_json().encode()
        if r.similar:
            body = page_cache.put(key, body)
    return _json(body)


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


_memo_jobs: dict[str, "asyncio.Task"] = {}


class _QuietEmitter:
    """Stands in for runs.Emitter when there is no run to put feed events on."""
    def __getattr__(self, name):
        return lambda *a, **kw: None

    def __call__(self, *a, **kw):
        return None


@app.post("/api/funds/{fund_id}/memos")
async def write_top_memos(fund_id: str, top: int = Query(5, ge=1, le=10), wait: bool = False) -> dict:
    """Write the missing memos for the fund's current top deals, in the background (feed events on the last run)."""
    run = store.latest_run(fund_id)
    if not config.live_ready():
        raise HTTPException(503, "The live agents aren't available right now.")
    job = _memo_jobs.get(fund_id)
    if job is None or job.done():
        from .agents.runner import write_top_memos as _write
        # Feed events go on the fund's last run; a seeded fund with no run gets a quiet emitter.
        emit = runs.Emitter(run["id"]) if run else _QuietEmitter()
        _memo_jobs[fund_id] = asyncio.ensure_future(_write(run["id"] if run else "", fund_id, emit, top=top))
    if wait:  # hold the request open until they're written (hosted: the container stays up meanwhile)
        written = await _memo_jobs[fund_id]
        return {"fund_id": fund_id, "top": top, "status": "done", "written": [m.id for m in written]}
    return {"fund_id": fund_id, "top": top, "status": "writing"}


@app.get("/api/funds/{fund_id}/memos/status")
def top_memos_status(fund_id: str) -> dict:
    job = _memo_jobs.get(fund_id)
    return {"fund_id": fund_id, "status": "idle" if job is None else ("done" if job.done() else "writing")}


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
