// Typed client for every endpoint in shared/contract.md.
// VITE_USE_MOCKS=true (default) reads src/mocks/*.json; false calls the FastAPI backend at VITE_API_BASE.
// In live mode a GET that fails at the network level (backend down) falls back to the mock, so the demo never dies.

import type {
  AgentEvent,
  AskCreated,
  QuestionItem,
  QuestionsResponse,
  Backtest,
  Company,
  CompanyDetail,
  DealStatus,
  DealsResponse,
  Feedback,
  FundResponse,
  FundsResponse,
  MapQuery,
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
} from "./types";

export const USE_MOCKS: boolean = import.meta.env.VITE_USE_MOCKS !== "false";
export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

/** Thrown for HTTP 4xx/5xx. `message` is the backend's plain-English `error`. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// ---------------------------------------------------------------------------
// Mocks (lazy-loaded so the live bundle stays small)
// ---------------------------------------------------------------------------

const mockLoaders = {
  fund: () => import("@/mocks/fund.json"),
  deals: () => import("@/mocks/deals.json"),
  portfolio: () => import("@/mocks/portfolio.json"),
  map: () => import("@/mocks/map.json"),
  memos: () => import("@/mocks/memos.json"),
  memo: () => import("@/mocks/memo.json"),
  universe: () => import("@/mocks/universe.json"),
  backtest: () => import("@/mocks/backtest.json"),
  run: () => import("@/mocks/run.json"),
  events: () => import("@/mocks/research_events.json"),
};
type MockName = keyof typeof mockLoaders;

const MOCK_LATENCY_MS = 120;
const wait = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

async function mock<T>(name: MockName): Promise<T> {
  const mod = await mockLoaders[name]();
  return structuredClone(mod.default) as unknown as T;
}

async function mockReply<T>(name: MockName): Promise<T> {
  await wait(MOCK_LATENCY_MS);
  return mock<T>(name);
}

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------

type Query = Record<string, string | number | boolean | null | undefined>;

function buildUrl(path: string, query?: Query): string {
  const url = new URL(path, API_BASE);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, String(v));
    }
  }
  return url.toString();
}

async function http<T>(method: "GET" | "POST", path: string, opts: { query?: Query; body?: unknown } = {}): Promise<T> {
  const res = await fetch(buildUrl(path, opts.query), {
    method,
    headers: opts.body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const err = (await res.json()) as { error?: string };
      if (err.error) message = err.error;
    } catch {
      /* body wasn't JSON */
    }
    throw new ApiError(res.status, message);
  }
  return (await res.json()) as T;
}

/** GET from the backend; if the backend can't be reached at all, fall back to the mock. */
async function get<T>(path: string, query: Query | undefined, fallback: () => Promise<T>): Promise<T> {
  try {
    return await http<T>("GET", path, { query });
  } catch (e) {
    if (e instanceof ApiError) throw e;
    console.warn(`[api] ${path} unreachable, using mock data`, e);
    return fallback();
  }
}

const post = <T>(path: string, body: unknown) => http<T>("POST", path, { body });

// ---------------------------------------------------------------------------
// Page endpoints
// ---------------------------------------------------------------------------

/** GET /api/fund: sidebar (fund tile, funds you cover, Deal Flow badge, watch card), landing window. */
export function getFund(fundId?: string): Promise<FundResponse> {
  if (USE_MOCKS) return mockReply("fund");
  return get("/api/fund", { fund_id: fundId }, () => mock("fund"));
}

/** GET /api/funds: every fund the sidebar can switch to. Without a backend: the funds in the mock. */
export function listFunds(): Promise<FundsResponse> {
  const fromMock = async (): Promise<FundsResponse> => {
    const f = await mockReply<FundResponse>("fund");
    return {
      items: f.covered_funds.map((c) => ({
        id: c.id,
        name: c.name,
        url: c.id === f.fund.id ? f.fund.url : `https://${c.id}.com`,
        logo: c.id === f.fund.id ? f.fund.logo : null,
        initials: c.name.replace(/[^A-Z]/g, "").slice(0, 3) || c.name.slice(0, 2).toUpperCase(),
        latest_run_id: c.id === f.fund.id ? f.latest_run_id : null,
        last_run_at: null,
        has_results: c.id === f.fund.id,
      })),
    };
  };
  if (USE_MOCKS) return fromMock();
  return get("/api/funds", undefined, fromMock);
}

export interface DealsQuery {
  fund_id?: string;
  status?: DealStatus;
  sector?: string;
  sort?: "fit";
}

/** GET /api/deals. `counts` always holds the totals, whatever the filter. */
export async function getDeals(q: DealsQuery = {}): Promise<DealsResponse> {
  const fromMock = async () => {
    const data = await mockReply<DealsResponse>("deals");
    data.items = data.items.filter(
      (d) => (!q.status || d.status === q.status) && (!q.sector || d.company.sector === q.sector),
    );
    return data;
  };
  if (USE_MOCKS) return fromMock();
  return get("/api/deals", { ...q }, fromMock);
}

/** GET /api/portfolio. */
export function getPortfolio(fundId?: string): Promise<PortfolioResponse> {
  if (USE_MOCKS) return mockReply("portfolio");
  return get("/api/portfolio", { fund_id: fundId }, () => mock("portfolio"));
}

/** GET /api/map: nodes + edges for React Flow, plus the Next deals shortlist. */
export function getMap(fundId?: string, q: MapQuery = {}): Promise<MapResponse> {
  if (USE_MOCKS) return mockReply("map");
  return get("/api/map", { fund_id: fundId, ...q }, () => mock("map"));
}

/** GET /api/memos: Investment Memos list. */
export function getMemos(fundId?: string): Promise<MemosResponse> {
  if (USE_MOCKS) return mockReply("memos");
  return get("/api/memos", { fund_id: fundId }, () => mock("memos"));
}

async function mockMemo(id: string): Promise<Memo> {
  const memo = await mockReply<Memo>("memo");
  if (memo.id !== id && memo.company.id !== id) throw new ApiError(404, "No memo yet for this company");
  return memo;
}

/** GET /api/memos/{id}. `id` is the company id, e.g. "northbeam-health". 404 -> ApiError. */
export function getMemo(id: string, fundId?: string): Promise<Memo> {
  if (USE_MOCKS) return mockMemo(id);
  return get(`/api/memos/${encodeURIComponent(id)}`, { fund_id: fundId }, () => mockMemo(id));
}

export interface UniverseQuery {
  q?: string;
  page?: number;
  page_size?: number;
  sector?: string;
  country?: string;
  stage?: string;
  founded?: number;
  fund_id?: string;
  /** Default: best fit first when the fund has scores, else dataset order. */
  sort?: "fit" | "name" | "founded" | "funding";
}

/** GET /api/universe: the dataset table. In mock mode filters the 8 sample rows client-side. */
export async function getUniverse(q: UniverseQuery = {}): Promise<UniverseResponse> {
  const fromMock = async () => {
    const data = await mockReply<UniverseResponse>("universe");
    const needle = q.q?.trim().toLowerCase();
    const filtered = data.items.filter(({ company: c }) => {
      if (needle && !`${c.name} ${c.one_liner}`.toLowerCase().includes(needle)) return false;
      if (q.sector && c.sector !== q.sector) return false;
      if (q.country && c.country !== q.country) return false;
      if (q.stage && c.stage !== q.stage) return false;
      if (q.founded && c.founded !== q.founded) return false;
      return true;
    });
    const isFiltered = Boolean(needle || q.sector || q.country || q.stage || q.founded);
    if (isFiltered) data.total = filtered.length;
    data.items = filtered;
    return data;
  };
  if (USE_MOCKS) return fromMock();
  return get("/api/universe", { ...q }, fromMock);
}

/** GET /api/backtest. 404 ApiError if no backtest yet. Mock numbers are design placeholders. */
export function getBacktest(fundId?: string): Promise<Backtest> {
  // The mock belongs to the demo fund only; any other fund has "no backtest yet".
  const fromMock = async () => {
    const bt = await mockReply<Backtest>("backtest");
    if (fundId && fundId !== bt.fund_id) throw new ApiError(404, "No backtest yet for this fund");
    return bt;
  };
  if (USE_MOCKS) return fromMock();
  return get("/api/backtest", { fund_id: fundId }, fromMock);
}

/** Funds with enough dated deals in the dataset for a fair backtest (shared/contract.md, GET /api/backtest).
 *  The Startup Universe offers these when the current fund has too little history. */
export const BACKTEST_FUNDS: { id: string; name: string }[] = [
  { id: "y-combinator", name: "Y Combinator" },
  { id: "european-commission", name: "European Commission" },
];

// ---------------------------------------------------------------------------
// Runs (the analyst team)
// ---------------------------------------------------------------------------

export const DEMO_RUN_ID = "run_demo_localglobe";

/** POST /api/runs. Then navigate to /research and open the event stream. */
export async function createRun(body: RunCreate): Promise<RunCreated> {
  if (USE_MOCKS) {
    await wait(MOCK_LATENCY_MS);
    return { run_id: DEMO_RUN_ID, fund_id: "localglobe" };
  }
  try {
    return await post<RunCreated>("/api/runs", body);
  } catch (e) {
    if (e instanceof ApiError) throw e;
    // Backend unreachable: show the recorded demo run instead (the event stream falls back to the mock too).
    console.warn("[api] /api/runs unreachable, showing the recorded run", e);
    return { run_id: DEMO_RUN_ID, fund_id: "localglobe" };
  }
}

/** GET /api/runs/{id}: Research page snapshot (mock is frozen at 2:14, step 4 of 7). */
export function getRun(runId: string): Promise<RunState> {
  if (USE_MOCKS) return mockReply("run");
  return get(`/api/runs/${encodeURIComponent(runId)}`, undefined, () => mock("run"));
}

/** GET /api/runs/{id}/memo/{company_id}: may take ~1 min live if the memo isn't written yet. */
export function getRunMemo(runId: string, companyId: string): Promise<Memo> {
  if (USE_MOCKS) return mockMemo(companyId);
  return get(
    `/api/runs/${encodeURIComponent(runId)}/memo/${encodeURIComponent(companyId)}`,
    undefined,
    () => mockMemo(companyId),
  );
}

/** POST /api/runs/{id}/feedback: records the partner's decision. Never contacts anyone. */
export async function sendFeedback(runId: string, body: Feedback): Promise<Ok> {
  if (USE_MOCKS) {
    await wait(MOCK_LATENCY_MS);
    return { ok: true };
  }
  return post(`/api/runs/${encodeURIComponent(runId)}/feedback`, body);
}

/** POST /api/funds/{id}/watch. `simulate_next_run: true` starts a re-run and returns its run_id. */
export async function setWatch(fundId: string, body: WatchRequest): Promise<WatchResponse> {
  if (USE_MOCKS) {
    const fund = await mockReply<FundResponse>("fund");
    return {
      watch: { ...fund.watch, enabled: body.enabled },
      run_id: body.simulate_next_run ? DEMO_RUN_ID : null,
    };
  }
  return post(`/api/funds/${encodeURIComponent(fundId)}/watch`, body);
}

async function mockCompany(id: string): Promise<Company> {
  await wait(MOCK_LATENCY_MS);
  const [deals, portfolio, universe, map, memo] = await Promise.all([
    mock<DealsResponse>("deals"),
    mock<PortfolioResponse>("portfolio"),
    mock<UniverseResponse>("universe"),
    mock<MapResponse>("map"),
    mock<Memo>("memo"),
  ]);
  const all: Company[] = [
    ...deals.items.map((d) => d.company),
    ...portfolio.columns.flatMap((c) => c.items.map((i) => i.company)),
    ...universe.items.map((u) => u.company),
    ...map.shortlist.map((d) => d.company),
    memo.company,
  ];
  const found = all.find((c) => c.id === id);
  if (!found) throw new ApiError(404, "We don't know this company yet");
  return found;
}

/** GET /api/companies/{id}/detail: everything about a company and how it scored for the fund. */
export async function getCompanyDetail(id: string, fundId?: string): Promise<CompanyDetail> {
  if (USE_MOCKS) {
    const company = await mockCompany(id);
    return {
      company, fund_id: fundId ?? "localglobe", fund_name: "LocalGlobe", in_dataset: false, summary: null,
      problem: null, business_model: null, customers: null, stage_estimated: false, market: null, funding: null,
      score: { scored: false, fit: null, model_fit: null, judge: null, rank: null, source_label: "Not scored for this fund yet",
        parts: [], reasons: [], why: [], feature_weights: [], nearest_portfolio: [] },
      signals: [], deal_status: null, health: null, conflict_with: null, memo_id: null, similar: [], similar_source: "", sources: [],
    };
  }
  return http<CompanyDetail>("GET", `/api/companies/${encodeURIComponent(id)}/detail`, { query: { fund_id: fundId } });
}

/** Logo paths the backend serves ("/api/logos/...") become absolute URLs on the API host. */
export function assetUrl(path: string | null | undefined): string | null {
  if (!path) return null;
  return path.startsWith("/api/") ? `${API_BASE.replace(/\/$/, "")}${path}` : path;
}

/** GET /api/companies/{id}. */
export function getCompany(id: string): Promise<Company> {
  if (USE_MOCKS) return mockCompany(id);
  return get(`/api/companies/${encodeURIComponent(id)}`, undefined, () => mockCompany(id));
}

// ---------------------------------------------------------------------------
// SSE: GET /api/runs/{id}/events
// ---------------------------------------------------------------------------

export interface RunEventHandlers {
  /** Called once per AgentEvent, in seq order, never twice for the same seq. */
  onEvent: (event: AgentEvent) => void;
  /** The run finished (Partner `done` with data.run_done, or a Partner `error`). */
  onDone?: () => void;
  /** Connection problem (live mode). EventSource keeps retrying unless you call close(). */
  onError?: (err: Event | Error) => void;
}

export interface RunEventOptions {
  /** Mock replay speed multiplier. 1 = the recorded gaps between events (3:44 total). */
  speed?: number;
  /** Mock: emit every event with elapsed_s <= startAt at once, then replay the rest live.
   *  e.g. 134 to open the page at the design moment (2:14). */
  startAt?: number;
  /** Live: replay speed sent to the backend as ?speed= (only when set and not 1). */
  liveSpeed?: number;
}

/** Live mode: connection failures before the first event, after which we replay the recorded run instead. */
const LIVE_FAILS_BEFORE_FALLBACK = 2;

export function isRunFinished(e: AgentEvent): boolean {
  return (
    e.agent === "Partner" &&
    ((e.type === "done" && (e.data as { run_done?: boolean }).run_done === true) || e.type === "error")
  );
}

/** Subscribe to a run's events. Returns a function that closes the stream. */
export function streamRunEvents(
  runId: string,
  handlers: RunEventHandlers,
  options: RunEventOptions = {},
): () => void {
  let lastSeq = 0;
  let closed = false;
  const deliver = (e: AgentEvent): boolean => {
    if (closed || e.seq <= lastSeq) return false;
    lastSeq = e.seq;
    handlers.onEvent(e);
    if (isRunFinished(e)) {
      closed = true;
      handlers.onDone?.();
      return true;
    }
    return false;
  };

  if (USE_MOCKS) return replayMockEvents(deliver, () => closed, () => (closed = true), options);

  const speed = options.liveSpeed && options.liveSpeed !== 1 ? options.liveSpeed : undefined;
  const source = new EventSource(buildUrl(`/api/runs/${encodeURIComponent(runId)}/events`, { speed }));
  let fails = 0;
  let stopMock: (() => void) | null = null;
  source.addEventListener("agent", (msg) => {
    try {
      if (deliver(JSON.parse((msg as MessageEvent<string>).data) as AgentEvent)) source.close();
    } catch (err) {
      console.warn("[api] bad SSE message", err);
    }
  });
  source.onerror = (err) => {
    if (closed) return;
    // A 404 (unknown run) or a backend that never answered: show the recorded run, already finished, so the page never dies and never re-runs.
    if (lastSeq === 0 && (++fails >= LIVE_FAILS_BEFORE_FALLBACK || source.readyState === EventSource.CLOSED)) {
      source.close();
      console.warn("[api] event stream unavailable, replaying the recorded run");
      stopMock = replayMockEvents(deliver, () => closed, () => (closed = true), { ...options, startAt: Number.MAX_SAFE_INTEGER });
      return;
    }
    handlers.onError?.(err);
  };
  return () => {
    closed = true;
    source.close();
    stopMock?.();
  };
}

function replayMockEvents(
  deliver: (e: AgentEvent) => boolean,
  isClosed: () => boolean,
  close: () => void,
  { speed = 1, startAt = 0 }: RunEventOptions,
): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  void mock<AgentEvent[]>("events").then((events) => {
    if (isClosed()) return;
    let i = 0;
    // Everything up to startAt arrives at once (like the backend replaying past events on connect).
    while (i < events.length && events[i].elapsed_s <= startAt) {
      if (deliver(events[i++])) return;
    }
    const next = () => {
      if (isClosed() || i >= events.length) return;
      const prevT = i === 0 ? startAt : Math.max(startAt, events[i - 1].elapsed_s);
      const gapMs = ((events[i].elapsed_s - prevT) * 1000) / Math.max(speed, 0.01);
      timer = setTimeout(() => {
        if (deliver(events[i++])) return;
        next();
      }, gapMs);
    };
    next();
  });
  return () => {
    close();
    if (timer) clearTimeout(timer);
  };
}

// ---------------------------------------------------------------------------
// Ask the team: POST /api/runs/{id}/ask, GET /api/funds/{id}/questions
// ---------------------------------------------------------------------------

/** Ask the analyst team a question about this run's fund. The work streams into the run's events. */
export function askTeam(runId: string, question: string): Promise<AskCreated> {
  if (USE_MOCKS) return Promise.reject(new ApiError(503, "Questions need the live backend."));
  return post<AskCreated>(`/api/runs/${encodeURIComponent(runId)}/ask`, { question });
}

/** Chat history for a fund (oldest first). */
export function getQuestions(fundId: string): Promise<QuestionsResponse> {
  if (USE_MOCKS) return Promise.resolve({ items: [] });
  return get<QuestionsResponse>(`/api/funds/${encodeURIComponent(fundId)}/questions`, undefined, async () => ({ items: [] }));
}

export function getQuestion(id: string): Promise<QuestionItem> {
  return http<QuestionItem>("GET", `/api/questions/${encodeURIComponent(id)}`);
}

/** Follow a run's events after `afterSeq` (stays open past the run's end while a question is answered).
 *  Closes itself once the `answer` event for `questionId` arrives. Returns a close function. */
export function followQuestion(runId: string, afterSeq: number, questionId: string, onEvent: (e: AgentEvent) => void): () => void {
  if (USE_MOCKS) return () => {};
  const source = new EventSource(buildUrl(`/api/runs/${encodeURIComponent(runId)}/events`, { last_event_id: afterSeq }));
  source.addEventListener("agent", (msg) => {
    try {
      const e = JSON.parse((msg as MessageEvent<string>).data) as AgentEvent;
      onEvent(e);
      if (e.type === "answer" && (e.data as { question_id?: string }).question_id === questionId) source.close();
    } catch (err) {
      console.warn("[api] bad SSE message", err);
    }
  });
  return () => source.close();
}
