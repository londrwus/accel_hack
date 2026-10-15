# Next session: build plan (Frontend · Backend · Model)

The user has opted in to running this as **workflows** (multi-agent). Three tracks run in parallel after a short shared step.
Read `CLAUDE.md`, `docs/DESIGN.md`, `docs/ARCHITECTURE.md` and `docs/DATA.md` first.

## What the user will bring
- The startup dataset (~10k rows: idea, bio, geo, business, …). Put it at `data/companies.csv` (git-ignored if private).
- A Modal token. **Modal is not logged in on this machine yet**: the CLI profile `bernararno17` exists but has no token.
  The user runs `! modal token new` (or `! modal token set --token-id … --token-secret …`).
- An Anthropic API key in `.env`.

## Machine facts (checked)
- Windows 11 · Python 3.12 · Node 22.20 / npm 10.9 · git 2.47 · Modal CLI 1.5.2 · **uv 0.13.1** installed via pip. It isn't on PATH,
  so call it as `python -m uv …` (or add `%APPDATA%\Python\Python312\Scripts` to PATH).
- Modal CLI on Windows needs **`PYTHONUTF8=1`**, otherwise it crashes on unicode output (`charmap` codec errors).
- Modal skill + 218 local doc pages are installed at `~/.claude/skills/modal/references/`. Read them before writing Modal code.
- No Docker. Keep local CPU/RAM light. All embedding and training runs on Modal.

## Design hand-off (already exported)
- `design/screens/*.png`: pixel references for every page at 1440×900 (landing is taller). **The frontend must match these 1:1.**
  `0-components` · `1-landing` · `2-deal-flow` · `3-portfolio` · `4-research` · `5-market-map` · `6-investment-memo` · `7-startup-universe`
- `design/export/*.html`: Pencil's Tailwind HTML export (landing, app pages, components), with layer names as data attributes.
  Use it for exact spacing, sizes and colours. Rebuild it as clean React components; don't paste the HTML in.
- `design/assets/logos/`: real company logos. `design/assets/botanical-band.png`: the landing painting.
- Source of truth: `C:\Users\Lenovo\Documents\accel.pen` (open in pen.dev; read it via the pencil MCP, never as a file).
  Re-export with the pencil `execute` → `Export(...)` if a design changes.
- Tokens (Pencil variables → Tailwind theme): bg `#F1EEE8`, shell `#EFEDE8`, panel `#FFFFFF`, surface `#FAF8F4`, ink `#1A1817`,
  muted `#6B675F`, subtle `#9A958B`, hair `#E7E3DC`, chip `#1A18170D`, cta/gold `#D8B56A`, sage `#A3BBA6`, accent `#5C7A63`,
  accent-soft `#E2EAE1`, predicted `#B8892E`, predicted-soft `#F4E9CF`, competitor `#BDB7AC`, warning `#A85A2A`, warning-soft `#F5E6DA`,
  danger `#B4432A`. Fonts: Hanken Grotesk (350/400/500), JetBrains Mono.

## Step 0: shared contract (do first, ~15 min, single agent)
Write `shared/contract.md` plus `backend/app/models.py` (Pydantic) and `frontend/src/lib/types.ts` (TS) with the same shapes:
`Fund`, `FundDNA`, `Company`, `Signal {kind: timing|strength|info|risk, label, icon, source_url}`, `DealFlowItem`, `PortfolioItem
{health: good|watch|at_risk|exited}`, `GraphNode/Edge`, `Memo {claims[{text, source, verified}]}`, `AgentEvent`, `Backtest`.
Also write `frontend/src/mocks/*.json` with the exact demo data shown in the designs, so the frontend never blocks on the backend.

## Track 1: Frontend (Vite + React + TS + Tailwind v4 + shadcn/ui + React Flow + Motion)
1. Scaffold `frontend/`, add tokens to the Tailwind theme, load the fonts, configure shadcn.
2. Build the components from the `Components` frame: `Button` (gold / white / ghost), `NavItem`, `Badge`, `Segmented`, `Chip`, `SignalChip`,
   `DataCard` (segmented bar + legend), `Sidebar` (watch card with mesh gradient, progress ring), `AppShell` (sidebar + inset white panel).
3. Pages (routes from `DESIGN.md`): `/` landing, `/deals`, `/portfolio`, `/research`, `/map`, `/memos/:id`, `/universe`.
4. Motion from `DESIGN.md` (per-letter headline rise, fade-ups, live feed slide-in, map nodes scale-in, gold pulse).
5. **Visual check loop per page**: run dev server → screenshot at 1440×900 (pencil `browser` tool: `load-page` + `return-screenshot`)
   → compare with `design/screens/N-*.png` → fix → repeat until it matches.
6. `src/lib/api.ts`: switch between mocks and the live API with `VITE_USE_MOCKS`. Use SSE for `/research`.

## Track 2: Backend (FastAPI, Python 3.12, uv, SQLite)
1. `backend/`: `python -m uv init`, FastAPI app, CORS, `.env` loading, SQLite store (runs, events, memory, feedback).
2. Endpoints from `ARCHITECTURE.md` plus page endpoints: `GET /api/deals`, `/api/portfolio`, `/api/map`, `/api/memos/:id`, `/api/universe?q=&page=`,
   `/api/backtest`, `POST /api/runs`, `GET /api/runs/:id/events` (SSE).
3. Agents: orchestrator ("Partner") + Reader, Thesis, Market, Mapper, Deal Finder, Analyst, Critic, using Claude (`claude-opus-5-5` orchestrator,
   `claude-sonnet-5-5` workers, `claude-haiku-5-5` extraction). Load the `claude-api` skill before writing agent code. Every event message is in plain English.
4. Retries + checkpoints + `recovered` events. Prompt-injection guard on fetched pages. `DEMO_MODE=replay` records and replays event logs.
5. `modal_client.py` calls the deployed Modal functions, with a timeout and a cached fallback.

## Track 3: Model on Modal (shallow on purpose)
1. Inspect the CSV → write `data/SCHEMA.md` and map columns. **Drop founder gender, age, ethnicity, nationality and photo columns.**
2. `ml/modal_app.py`: Volume `bellwether-data`. `embed_all` (small open embedding model) · `similar_companies(query, k)` ·
   `score_fit(fund_dna, portfolio, k)` (per-fund logistic regression on similarity + sector/stage/geo/recency, returning feature contributions) ·
   `backtest(fund)` (hold out the last 20 portfolio deals, top-5% hit rate vs keyword and random) → `data/cache/backtest_{fund}.json`.
3. Deploy with `PYTHONUTF8=1 modal deploy ml/modal_app.py`. Smoke-test each function from the backend.
4. The Startup Universe page shows **only real backtest output**. If there isn't enough history, show "Not enough history".

## Definition of done (for the demo)
- `/` → paste the LocalGlobe URL → `/research` streams real agent events → Deal Flow, Map and Memo fill with real data → the Universe page shows the real backtest.
- Every page matches its design PNG at 1440×900.
- `DEMO_MODE=replay` works with Wi-Fi off.
