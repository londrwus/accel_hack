# CLAUDE.md

Context for Claude Code sessions working in this repo. Read this first, then `docs/` as needed.

## What we're building

**Bellwether**, an operating system for venture funds that runs on its own.
You paste a VC fund's website URL. A team of long-running Claude agents then:

1. **Reads the fund**: website, portfolio, team, blog posts, news. It writes down the fund's *thesis*.
2. **Maps the portfolio**: what each company does and who it competes with, shown as a node map.
3. **Predicts the next deals**: ranks ~10k startups against the thesis and explains each pick.
4. **Writes the due diligence**: a one-page memo for the top pick, with sources, risks and open questions.
5. **Keeps watching**: re-runs on a schedule and flags what changed ("the always-on analyst").

Pitch line: *"The first fully systematic VC analyst. It never sleeps, and a human always makes the call."*

Event: Accel AI Innovate London hackathon. The theme is **long-running agents**. See `docs/STRATEGY.md` for the judging rubric.

## Golden rules

- **The demo is the product.** Every feature must be visible on screen within 5 minutes. If the audience can't see it, don't build it.
- **Plain language everywhere.** UI copy must make sense to a non-technical person. Say "Companies like this" instead of "cosine-similar embeddings".
- **Few pages.** We have a one-page landing plus 6 platform pages (Deal Flow, Portfolio, Research, Market Map, Investment Memos, Startup Universe) (see `docs/DESIGN.md`). Don't add routes without updating that doc.
- **Show the agents working.** Stream agent steps live (SSE). The agent activity feed is the core of the "long-running agents" score.
- **Always have a fallback.** Every live call has a cached/replay path so the demo never dies on stage (`DEMO_MODE=replay`).
- **Cite everything.** Every claim in a memo links to a source URL or a row in the dataset.
- **Humans decide.** The system recommends and drafts. It never contacts founders or commits money.
- Hackathon pace: simple and working beats clever. No deep ML, no premature abstractions.

## Local machine constraints (Windows 11)

- **No Docker**, no WSL-only tooling, no local databases that need a server (no Postgres/Redis). Use SQLite + files.
- Keep local CPU/RAM usage low. Run only the FastAPI process and the Vite dev server locally.
- **All model training and embedding runs on Modal.** Nothing heavy runs locally: no torch, no local LLMs, no sentence-transformers.
  The backend calls the deployed Modal functions over HTTP/SDK.
- Use `uv` for Python and `npm` for Node. Commands must work in PowerShell.
- Load the 10k CSV with the stdlib `csv` module or a light pandas read once at startup. Don't keep big copies in memory.

## Stack

| Layer | Choice |
|---|---|
| Frontend | Vite + React + TypeScript, Tailwind CSS v4, shadcn/ui, React Flow (node map), Motion (Framer Motion). Visual style: light-theme Lightfern clone, see `docs/DESIGN.md` |
| Backend | Python 3.11+, FastAPI, SSE for the agent event stream, Pydantic models |
| Agents | Anthropic API (Claude). Orchestrator `claude-opus-5-5`; workers `claude-sonnet-5-5`; cheap extraction `claude-haiku-5-5` |
| Web data | Server-side fetch + Claude web search tool (or a search API) |
| ML | Simple: embeddings + similarity + a light scoring model over the ~10k company CSV, hosted on **Modal** |
| Storage | SQLite (runs, events, memory) + JSON cache files for demo replay |
| Design | pen.dev, file `accel.pen` (outside repo: `C:\Users\Lenovo\Documents\accel.pen`) |

## Repo layout (target)

```
/CLAUDE.md, /README.md
/docs/            strategy, pitch, product, architecture, design, data, responsible AI, plan, tasks
/backend/         FastAPI app (app/main.py, app/agents/, app/tools/, app/models.py, app/store.py)
/frontend/        Vite app (src/pages/, src/components/, src/lib/api.ts)
/ml/              Modal app: embed + score companies (modal_app.py)
/data/            companies.csv (not committed if large/private), demo cache/
```

## Commands

`uv` is not on PATH on this machine, so call it as `python -m uv`. Backend commands run from `backend\`:

- Backend install: `python -m uv sync`
- Backend run: `python -m uv run uvicorn app.main:app --port 8000` (add `--reload` while developing)
- Backend tests: `python -m uv run pytest -q` (never call Claude or Modal; the key is blanked in `tests/conftest.py`)
- Status check: `curl localhost:8000/api/health` (demo mode, key present, Modal deployed or fallback, CSV present)
- Quick replay: `curl -X POST "localhost:8000/api/runs?speed=10" -H "Content-Type: application/json" -d '{"fund_url":"https://localglobe.vc"}'`, then `curl -N localhost:8000/api/runs/<run_id>/events`
- Settings live in the repo-root `.env` and are re-read on every call, so no restart is needed. `DEMO_MODE=replay` (default) replays a recording. `DEMO_MODE=live` plus `ANTHROPIC_API_KEY` runs the real agent team, which makes paid calls. A variable set in the shell beats the `.env`, even when it is empty. In PowerShell, use `$env:DEMO_MODE="replay"`.
- Frontend: `cd frontend && npm run dev`
- Modal (PowerShell, start at the repo root; always set `$env:PYTHONUTF8=1` first, or the CLI crashes on unicode):
  - Clean the data and upload it to the Volume: `python -I -X utf8 ml/prepare.py; python -I ml/upload.py`
  - Deploy: `cd ml; modal deploy modal_app.py`
  - Embed all companies (once, and again after the data changes): `modal run modal_app.py::embed_all` (from `ml/`)
  - Smoke tests: `modal run modal_app.py::smoke` and `modal run modal_app.py::smoke_fit` (from `ml/`)
  - Backtests into `data/cache/backtest_*.json`: `modal run modal_app.py::run_backtests` (from `ml/`)
  - Check the deployed app the way the backend calls it: `python -I ml/check_deployed.py --save-backtests` (repo root)
- Backend on Modal (public API for the Vercel frontend): `cd backend; $env:PYTHONUTF8=1; .venvScriptsmodal.exe deploy modal_web.py` serves https://hexagonterstretch--bellwether-web-web.modal.run (data in volume `bellwether-web-data` at /data, keys in secret `bellwether-secrets`; one warm container via min_containers=1, so set it to 0 after the event)

## Secrets

`.env` only, never committed: `ANTHROPIC_API_KEY`, `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`, optional `SEARCH_API_KEY`.

## Docs index

- `docs/STRATEGY.md`: judging rubric, how we score, odds of winning
- `docs/PITCH.md`: the 5-minute pitch and demo script, plus the table-pitch version
- `docs/PRODUCT.md`: customer, problem, user flow, scope
- `docs/ARCHITECTURE.md`: agent team, hand-offs, memory, error recovery, API
- `docs/DESIGN.md`: design system and screen specs (source of truth for the frontend)
- `docs/DATA.md`: the 10k company dataset and the simple ML model
- `docs/RESPONSIBLE_AI.md`: safety, privacy, misuse
- `docs/PLAN.md`: timeline
- `docs/TASKS.md`: task checklist
- **`docs/NEXT_SESSION.md`: start here next session.** It has the 3-track workflow plan (frontend 1:1 from design, backend, Modal model) and the machine setup facts
- `design/`: exported screen PNGs, Tailwind HTML exports, logos and the botanical image from `accel.pen`
