# API contract

The shared agreement between the frontend and the backend. The shapes live in two files that must stay identical:

- `backend/app/models.py` (Pydantic v2)
- `frontend/src/lib/types.ts` (TypeScript)

Example responses live in `frontend/src/mocks/*.json`. They hold the exact demo data from the design PNGs and
pass validation against `models.py`. If you change a shape, change all three places in the same commit.

## Conventions

- Base URL: `http://localhost:8000`. Every path starts with `/api`. JSON in, JSON out.
- Field names are **snake_case** on both sides. Nothing is camelCased.
- Optional fields are always sent. Missing values are `null`, never left out. (`Optional[X] = None` in Python, `X | null` in TS.)
- Times are ISO 8601 strings (`ts`, `created_at`, ...). Fields ending in `_label` are ready-made display text
  (`"2h"`, `"Updated 2d ago"`, `"7:00 tomorrow"`). The frontend shows them as they are.
- Scores: `fit` is an integer 0–100. `share` and `value` are floats 0–1.
- Every `message`, `label`, `why` and claim `text` is plain English and goes straight into the UI.
- Page endpoints take an optional `?fund_id=` (default: the current fund, `localglobe` in the demo).
- Errors: an HTTP 4xx/5xx status with the body `{"error": "Plain-English reason"}` (`ErrorResponse`).
- CORS allows `http://localhost:5173` (the Vite dev server).
- The frontend switches between mocks and the live API with `VITE_USE_MOCKS=true|false` (in `src/lib/api.ts`).

### Logos
- `Company.logo` / `GraphNode.logo` / `Fund.logo` hold a URL or a path like `/logos/cleo.png`.
- The frontend copies `design/assets/logos/*` to `frontend/public/logos/`, so mock paths resolve.
- Live: the backend fills every `Company.logo` / `GraphNode.logo` / `Fund.logo` it returns with, in order: the dataset logo
  (`/api/logos/dataset/<file>`), a logo fetched from the company's website and cached (`/api/logos/site/<file>`), the
  Google favicon for the domain, else `null`. Paths starting `/api/` are relative to the API base; the frontend prefixes them.
  Missing site logos are fetched in the background, so they appear on the next load (never blocks a page).
- `null` means "draw an initial tile" (the first letter of the name). Made-up companies (Northbeam Health, Ledgerly,
  Harbor Labs, ...) always have `logo: null`. Never invent a logo.

### Fixed meanings
| Value | Meaning in the UI |
|---|---|
| `Signal.kind = timing` | gold chip, e.g. *Raising now* |
| `Signal.kind = strength` | sage chip, e.g. *Revenue up 3×*, *Like BioOrbit* |
| `Signal.kind = info` | grey chip, e.g. *In Sifted this week* |
| `Signal.kind = risk` | terracotta chip, e.g. *Competes with Cleo* |
| `Signal.icon` | a lucide icon name (`trending-up`, `link`, `users`, `chart-line`, `triangle-alert`, `newspaper`, `award`, `landmark`, `handshake`, `layers`, `user-minus`, `timer`, `eye`, `briefcase`, `check`) |
| `PortfolioItem.health = at_risk` | column **Needs attention** (terracotta) |
| `health = watch` | column **Likely to raise soon** (gold) |
| `health = good` | column **Doing well** (sage) |
| `health = exited` | column **Exited** (faded) |
| `DealFlowItem.status` | `new` → "New", `under_review` → "Under review", `passed` → "Passed" (row faded) |
| `GraphNode.kind` | `fund` pale sage centre · `portfolio` sage · `competitor` grey · `pick` gold with fit pill |
| `GraphEdge.kind` | `owns` fund→portfolio (grey) · `competes` portfolio→competitor (grey) · `similar` pick→portfolio it looks like (gold) · `candidate` fund→pick (faint gold) · `conflict` pick→portfolio it clashes with (red) |
| `Verdict` | `meeting` = "Move to first meeting", `pass` = "Pass", `dig_deeper` = "Dig deeper" |

## Endpoints

### Page endpoints (one per screen)

| Method | Path | Response | Mock | Used by |
|---|---|---|---|---|
| GET | `/api/fund` | `FundResponse` | `fund.json` | sidebar (fund tile, funds you cover, Deal Flow badge, watch card), landing window |
| GET | `/api/funds` | `FundsResponse` | (built from `fund.json`) | sidebar fund switcher + "Funds you cover" |
| GET | `/api/deals` | `DealsResponse` | `deals.json` | `/deals` |
| GET | `/api/portfolio` | `PortfolioResponse` | `portfolio.json` | `/portfolio` |
| GET | `/api/map?view=&center=&sector=&country=&stage=&limit=` | `MapResponse` | `map.json` | `/map`. `view`: `portfolio` (default, picks around what the fund owns) · `theme` (grouped by sector, `theme` hub nodes) · `new` (high fit, unlike anything owned) · `competition` (portfolio + rivals). `center`: any company id; the map re-centres on it with its nearest companies from Modal `similar_companies` (8s timeout, then cache, then word match) and their fit for the fund; the response then has `view: "center"`, `center_id`, and the centre is a `fund`-kind bubble with a `company_id`. `limit` 1..50 picks (default 10). Edges carry a plain-English `label` ("very similar", "same customers", "rival", "new bet"). Extra response fields: `view`, `center_id`, `note`, `sectors`, `countries`, `stages` (filter options) |
| GET | `/api/memos` | `MemosResponse` | `memos.json` | Investment Memos list (nav item) |
| GET | `/api/memos/{id}` | `Memo` | `memo.json` | `/memos/:id` |
| GET | `/api/universe` | `UniverseResponse` | `universe.json` | `/universe` table + KPI strip |
| GET | `/api/backtest` | `Backtest` | `backtest.json` | `/universe` KPI strip + right rail |

**`GET /api/deals`** query: `fund_id?`, `status?=new|under_review|passed`, `sector?`, `sort?=fit` (default: best fit first).
`counts` always holds the totals for the segmented control (All 61 / New 3 / Under review 12 / Passed 46), whatever the filter.

**`GET /api/universe`** query: `q?` (search name + one-liner), `page?=1`, `page_size?=50`, `sector?`, `country?`, `stage?`,
`founded?` (a year), `fund_id?`. `total` = rows that match, `dataset_size` = all rows (10,412). `fit` is the fit for the
current fund, or `null` if it hasn't been scored yet. The UI shows `row_id` as `#` + 4-digit zero-padded (`#0193`).
`sort?=fit|name|founded|funding` (default: best fit first when the fund has scores, else dataset order).
Each row also has `funding_usd` (total raised, or `null`), and the response has `options` (every sector, country, stage
and founded year in the dataset, for the filter menus; `null` without the CSV).

**`GET /api/funds`** returns `FundsResponse {items: FundSummary[]}`. `FundSummary {id, name, url, logo, initials,
latest_run_id, last_run_at, has_results}`. Lists the demo fund, the funds you cover, every fund with a run and every
fund with saved results; demo fund first, then most recently run. Every page endpoint takes `fund_id?` for the fund
picked in the sidebar (the UI keeps it in `?fund=` and localStorage).

**`GET /api/backtest`** query: `fund_id?`. In order:
1. `data/cache/backtest_{fund}.json` if it exists (the backend saves every Modal result there).
2. **Too few dated deals**: if the dataset has fewer than 25 of the fund's deals with a date, the response is
   **200** with `enough_history: false`, `held_out` (0 or the real count), `methods: []`, `feature_weights: []`,
   `score_seconds: 0` and a model card. It never sends numbers in this case. A Modal answer with fewer than 10
   held-out deals is turned into the same shape.
3. Otherwise the backend starts the Modal `backtest(fund)` job once and waits up to `MODAL_TIMEOUT_S`. A later request
   picks up the result when the job takes longer.
4. Nothing yet (job still running, Modal down): 404 `{"error": "..."}`, e.g. "No backtest yet for this fund".

If `enough_history` is `false`, the UI shows "Not enough history for this fund", no numbers, and offers a fund
that has results. The UI checks this short list in order: the current fund, then `y-combinator` (Y Combinator) and
`european-commission` (European Commission), the only funds with 25+ dated deals in the dataset. A 404 for one of
them just means "no results to offer yet". The numbers in `backtest.json` are design placeholders. Never show them on
stage as real results.

**`GET /api/memos/{id}`**: `id` is the company id (e.g. `northbeam-health`). 404 if there's no memo yet.

**Stage labels**: `Company.stage` is the dataset's `stage_label` (or `"Unknown"`). When the stage was worked out from
the latest funding round rather than reported directly, the backend may send it with an ` (estimated)` suffix, e.g.
`"Seed (estimated)"`. The UI shows the stage name and a subtle grey "estimated" label next to it. `"Unknown"` shows as a dash.

### Status and data controls

| Method | Path | Response | Used by |
|---|---|---|---|
| GET | `/api/health` | `{ok, demo_mode, live_agents, anthropic, anthropic_key, companies_csv, modal, modal_reason, modal_app, modal_configured, modal_functions, modal_timeout_s, modal_cache_files}` | checks before a demo (no UI) |
| DELETE | `/api/funds/{id}/data` | `Ok` | "Delete fund data" (docs/RESPONSIBLE_AI.md) |

- `GET /api/health`: `demo_mode` is `replay` or `live`; `live_agents` is true when a run would use the live team
  (live mode and an API key); `anthropic` is `"key present"` or `"no key"` (never the key itself); `companies_csv` says
  if `data/companies.csv` is there; `modal` is `"deployed"` or `"fallback"`, with `modal_reason` in plain English, and
  `modal_functions` maps each Modal function to `{status: "ok"|"fallback"|"untried", reason, seconds}`.
- `DELETE /api/funds/{id}/data`: removes the fund's runs, events, memory (saved pages, memos, scores, thesis weights,
  watch snapshot), feedback and watch schedule. 409 `{"error": ...}` while a run for that fund is still going.

### Runs (the analyst team)

| Method | Path | Body | Response | Mock |
|---|---|---|---|---|
| POST | `/api/runs` | `RunCreate {fund_url, task?}` | `RunCreated {run_id, fund_id}` | – |
| GET | `/api/runs/{id}` | – | `RunState` | `run.json` |
| GET | `/api/runs/{id}/events` | – | SSE stream of `AgentEvent` | `research_events.json` |
| GET | `/api/runs/{id}/memo/{company_id}` | – | `Memo` (written on demand if missing, which may take ~1 min) | `memo.json` |
| POST | `/api/runs/{id}/feedback` | `Feedback {company_id, verdict, note?}` | `Ok` | – |
| POST | `/api/funds/{id}/watch` | `WatchRequest {enabled, simulate_next_run}` | `WatchResponse {watch, run_id?}` | – |
| GET | `/api/companies/{id}` | – | `Company` | – |
| GET | `/api/companies/{id}/detail` | – | `CompanyDetail` | – |
| GET | `/api/logos/dataset/{file}` · `/api/logos/site/{file}` | – | image | – |
| POST | `/api/runs/{id}/ask` | `AskRequest {question}` | 202 `AskCreated {question_id, run_id}` | – |
| POST | `/api/funds/{id}/ask` | `AskRequest {question}` | 202 `AskCreated` (uses the fund's latest run, or opens a holder run) | – |
| GET | `/api/funds/{id}/questions` | – | `QuestionsResponse {items: QuestionItem[]}` (oldest first) | `{items: []}` |
| GET | `/api/questions/{id}` | – | `QuestionItem` | – |

- `GET /api/companies/{id}/detail?fund_id=`: the company page. `CompanyDetail` = `company`, `fund_id`, `fund_name`,
  `in_dataset`, `summary`/`problem`/`business_model`/`customers` (dataset text), `stage_estimated`, `market`
  (`MarketInfo {description, scope, size, cagr, year, source}`), `funding` (`FundingInfo {amount_label, last_round_date,
  first_round_date, rounds, investors}`, display only, never used for scoring), `score` (`CompanyScore {scored, fit,
  model_fit, judge, rank, source_label, parts: FitPart[], reasons: [{label, impact}], why, feature_weights,
  nearest_portfolio: [{company_id, name, score}]}`), `signals`, `deal_status`, `health` (when the fund owns it),
  `conflict_with`, `memo_id`, `similar: [{company, score}]` + `similar_source`, `sources: Source[]`.
  Score order: the fund's shortlist and latest run checkpoint → the Modal model's cached answer for the fund → the saved
  fit for every row plus a quick local breakdown → a quick local estimate → `scored: false` ("Not scored for this fund yet").
  "Companies like this" calls Modal `similar_companies` with a 3s timeout and falls back to word match.
- `POST /api/runs`: `task` defaults to "Find {fund}'s next 10 deals and write a memo for the best one". The run starts in
  the background; the frontend then navigates to `/research` and opens the event stream.
- `RunState` is the snapshot for the Research page: agent strip (`agents`), "Thought process" checklist (`plan`),
  "Step: 4 of 7" (the first `plan` step not `done`, counted 1-based), the request bubble (`task`), `partner_summary`,
  the "What {fund} invests in" card (`fund.dna.sectors`) and the gold "Since yesterday" note (`since_last_run`).
  `run.json` is frozen at the design moment (2:14 into the run).
- `feedback`: the verdict adjusts the thesis weights for the next run and sets `Memo.decision`.
  Bellwether never contacts founders. "Move to first meeting" only records the decision.
- `ask` ("Ask the team", the chat on /research): the Partner routes the question to 1-3 of Market, Analyst, Deal Finder,
  Mapper, Thesis, Critic; they work in parallel on the run's stored context (fund DNA, portfolio, deals, memos, map) with
  web search, the dataset and Modal `similar_companies`; the Partner then writes a short cited answer. Every step is an
  `AgentEvent` in the run's feed with `tag: "Question"` and `data.question_id`; the last is a Partner event of type
  `answer` with `data {question_id, answer (markdown, cites [n]), sources: AskSource[] {label, url?, company_id?},
  company_ids, personas, unsure}`. `QuestionItem {id, run_id, fund_id, question, status: working|answered|error,
  personas, answer, sources, company_ids, companies: Company[], unsure, asked_at, answered_at}` is saved in SQLite.
  While a question is being answered the run's event stream stays open past the run's end; open it with
  `?last_event_id=<last seq seen>` to follow the question. Nothing is ever sent to founders.
- `watch` with `simulate_next_run: true` starts a re-run straight away (the "Simulate next morning" button) and returns its `run_id`.

## SSE event stream

`GET /api/runs/{id}/events` returns `Content-Type: text/event-stream`. On connect it **replays every past event of the run**,
then streams new ones live. Each event is one SSE message:

```
id: 31
event: agent
data: {"seq":31,"ts":"2026-10-15T09:02:14Z","elapsed_s":134,"run_id":"run_demo_localglobe","agent":"Deal Finder","type":"finding","message":"Strong match: Northbeam Health. It looks like 3 companies LocalGlobe already owns.","tag":"New match","data":{"company_id":"northbeam-health","fit":94}}

```

- `event:` is always `agent`. `data:` is one `AgentEvent` as JSON on a single line. `id:` = `seq`, so a reconnect can
  send `Last-Event-ID` and get only newer events.
- The server sends a comment line `: ping` every 15 s to keep the connection open.
- Query options: `?last_event_id=N` does the same as the `Last-Event-ID` header; `?speed=x` (0 < x ≤ 100) speeds up a
  replayed run. `POST /api/runs?speed=x` sets the replay speed for the whole run.
- The stream closes after the run's final event (`agent: "Partner"`, `type: "done"`, `data.run_done: true`) or after an `error`
  event from the Partner. Use `new EventSource(url)` in the browser and `addEventListener("agent", ...)`.

### AgentEvent

| Field | Meaning |
|---|---|
| `seq` | 1, 2, 3 ... per run |
| `ts` | ISO time |
| `elapsed_s` | seconds since the run started. The feed shows it as `m:ss` (`134` → `2:14`) |
| `agent` | `Partner` · `Reader` · `Thesis` · `Market` · `Mapper` · `Deal Finder` · `Analyst` · `Critic` |
| `type` | see below |
| `message` | plain English, shown as-is |
| `tag` | the chip on the right of the feed row, or `null`. Values: `Plan`, `Hand-off`, `New match`, `Changed`, `Recovered`, `Retrying`, `Clash`, `Not verified`, `Done` |
| `data` | extra details (below). The UI must work if `data` is `{}` |

| `type` | When | Typical `data` |
|---|---|---|
| `plan` | the Partner wrote the plan | `{"steps": ["Read the website", ...]}` |
| `step` | an agent is doing something | `{}` |
| `tool` | an agent called a tool | `{"tool": "fetch_page" \| "web_search" \| "similar_companies" \| "score_fit", "url"?, "query"?}` |
| `handoff` | work moved between agents | `{"from": "Reader", "to": "Thesis" \| ["Deal Finder","Mapper"], "payload_summary": "42 portfolio companies"}` |
| `finding` | a result worth showing | `{"company_id"?, "fit"?, "memo_id"?, "change"?}` |
| `warning` | something went wrong, the agent is retrying | `{"url"?, "attempt"?, "ignored_instructions"?: true}` |
| `recovered` | a fallback worked (show the *Recovered* badge) | `{"url"?, "fallback": "search results"}` |
| `done` | an agent finished; with `run_done: true`, the whole run finished | `{"run_done"?: true, "memo_id"?, "concerns"?: ["..."]}` |
| `error` | an agent gave up | `{"reason"?}` |
| `answer` | the Partner's reply to a question (tag `Question`) | `{question_id, answer, sources, company_ids, personas, unsure}` |

**Plan progress**: any event may carry `data.plan_step` (1-based index into the plan) and `data.plan_status`
(`working` | `done`). The frontend uses these to tick the checklist and move the step counter live, without refetching `RunState`.

**Watch mode (`Changed`)**: on a re-run (scheduled, or "Simulate next morning") the Partner compares with the last run and
emits up to 6 `finding` events, most important first. `tag` is `New match` for a new pick and `Changed` for anything else.
`data.change` says what kind: `new_match` (`company_id`, `fit`), `health` (`company_id`), `competitor_raised`, `fit`
(`company_id`, `fit`), `new_competitors` (`count`), `dropped` (`company_id`). The same run's `RunState.since_last_run`
holds the one-line summary ("Since yesterday: 2 new matches, 1 competitor raised"). The UI shows `Changed` as a sage chip.

**Ignored instructions**: when a fetched page contains text that tries to instruct an AI, the agent emits a `warning`
with `tag: null` and `data.ignored_instructions: true` (and `data.url`). The message says it was ignored. The UI shows it
as a normal row with an "Ignored" chip; it is not a retry.

**Critic concerns**: the Critic's `done` event may carry `data.concerns`, up to 3 plain-English worries about the memo
(bias, conflicts of interest, over-confident wording). It is an untagged `done`, but when `concerns` is not empty the
UI shows it as a feed row with the concerns listed under the message.

**Agent strip**: an agent is `working` from its first event until its `done` event, `waiting` before its first event, and `done` after.

### Replay (`DEMO_MODE=replay`)
The backend streams a recorded log from `data/cache/{fund}.jsonl` (one `AgentEvent` per line) with the original gaps between
`elapsed_s` values. `frontend/src/mocks/research_events.json` holds the same events as one JSON array. Run id: `run_demo_localglobe`.

## Mock files

| File | Shape |
|---|---|
| `fund.json` | `FundResponse` |
| `deals.json` | `DealsResponse` (8 rows shown, counts 61/3/12/46) |
| `portfolio.json` | `PortfolioResponse` |
| `map.json` | `MapResponse` (19 nodes, 21 edges, top 3 shortlist). `x, y` = top-left of each node box in the 800×780 design canvas |
| `memos.json` | `MemosResponse` |
| `memo.json` | `Memo` for `northbeam-health` |
| `universe.json` | `UniverseResponse` (page 1, 8 rows) |
| `backtest.json` | `Backtest` (placeholder numbers from the design) |
| `run.json` | `RunState` frozen at 2:14 (step 4 of 7) |
| `research_events.json` | `AgentEvent[]`, 47 events over 3:44, including a retry → `recovered` and a portfolio clash |

The landing page's product window uses copy written into the landing page itself, plus `fund.json` (Fund DNA) and `deals.json` item #1.
