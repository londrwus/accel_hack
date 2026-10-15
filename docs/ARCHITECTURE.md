# Architecture

Keep it simple: one FastAPI process, one SQLite file, Claude agents called in-process, ML on Modal. No Docker.

```
 Browser (Vite/React)
   │  POST /api/runs  ─────────────┐
   │  GET  /api/runs/{id}/events (SSE: live agent feed)
   ▼                               ▼
 FastAPI ──► Orchestrator ("Partner", claude-opus-5-5)
               │ plans the run, hands tasks to workers, retries, checkpoints
   ┌───────────┼───────────┬────────────┬─────────────┬────────────┐
   ▼           ▼           ▼            ▼             ▼            ▼
 Reader     Thesis      Market       Mapper       Deal Finder   Analyst ──► Critic
 (site)     (fund DNA)  (news)       (graph)      (rank 10k)    (memo)      (checks)
   │                                    │             │
   └── web fetch / search tools         └── Modal: similar_companies(), score_fit()
                                                      │
 SQLite: runs, events, fund_memory, feedback   ◄──────┘    data/cache/ (replay JSON)
```

## The agent team

Each agent has one job, a plain-English name shown in the UI, and a typed output (Pydantic).

| Agent (UI name) | Model | Input → Output | Tools |
|---|---|---|---|
| **Partner** (orchestrator) | Opus | fund URL → plan (checklist), hand-offs, final summary | can call all workers; `retry`, `checkpoint` |
| **Reader** | Haiku/Sonnet | URL → pages, list of portfolio companies, team, blog topics | `fetch_page`, `find_links` |
| **Thesis** | Sonnet | Reader output + news → **Fund DNA** (sectors, stage, geo, check size, themes; each with evidence) | none (reasoning) |
| **Market** | Sonnet | fund name → recent deals, announcements, partner posts | `web_search`, `fetch_page` |
| **Mapper** | Sonnet | portfolio → competitors per company → graph nodes/edges | `similar_companies` (Modal), `web_search` |
| **Deal Finder** | Sonnet | Fund DNA → top 50 from 10k by model score → LLM re-rank to top 10 with "why", conflict check vs portfolio | `score_fit` (Modal), `get_company` |
| **Analyst** | Opus/Sonnet | top pick → one-page diligence memo with citations | `web_search`, `fetch_page`, `get_company` |
| **Critic** | Sonnet | memo → per-claim check (supported / unsupported), bias & conflict flags | `fetch_page` |

### Planning and hand-offs
- The Partner writes a plan of 6–8 steps first. It's shown as a checklist in the UI, and steps tick as they complete.
- Each hand-off is an explicit event: `{from: "Reader", to: "Thesis", payload_summary: "Found 42 portfolio companies"}`.
- Parallelism: Market and Mapper run while Thesis finishes, which makes the feed look alive.

### Memory
- `fund_memory` (SQLite): the latest Fund DNA, seen company IDs, shortlist history, partner feedback.
- On a re-run, agents get "what you knew last time" and report only **changes** (new matches, competitor news).
- Feedback: Approve/Pass adjusts the thesis weights (e.g. boost or penalise the sector or stage) for the next run. That's simple and visible.

### Long-running / watch mode
- `POST /api/funds/{id}/watch` schedules re-runs (an in-process APScheduler job; no extra services).
- For the demo, a "Simulate next morning" button triggers a re-run with a newer news window and shows a diff.

### Error recovery (must be visible)
- Every tool call has a timeout, 2 retries with backoff, and then a fallback (e.g. site blocked → search snippets → dataset row).
- Each step's output is checkpointed to SQLite, so a crashed run resumes from the last completed step.
- Recoveries are emitted as `recovered` events and shown in the feed with a small badge. Judges score error recovery, so show it.
- Agent output must validate against its Pydantic schema. If it doesn't, the agent gets one repair attempt with the validation error.

## Event stream (SSE)

```json
{ "ts": "...", "run_id": "...", "agent": "Mapper",
  "type": "plan|step|tool|handoff|finding|warning|recovered|done|error",
  "message": "Found 6 competitors for Marker", "data": { } }
```
`message` is always plain English, because it goes straight into the UI.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/runs` `{fund_url}` | start a run → `{run_id}` |
| GET | `/api/runs/{id}/events` | SSE live feed (replays history on connect) |
| GET | `/api/runs/{id}` | full state: plan, fund_dna, graph, shortlist, memos |
| GET | `/api/runs/{id}/memo/{company_id}` | memo (generated on demand if missing) |
| POST | `/api/runs/{id}/feedback` `{company_id, verdict, note}` | approve / pass |
| POST | `/api/funds/{id}/watch` | enable watch mode / simulate next run |
| GET | `/api/companies/{id}` | dataset row |

## Demo safety

- `DEMO_MODE=live|replay`. Replay streams a recorded event log with realistic timing, from `data/cache/{fund}.jsonl`.
- Every live run is recorded automatically, so any good rehearsal run becomes the backup.

## Backend layout

```
backend/app/
  main.py          FastAPI app, routes, SSE
  models.py        Pydantic: FundDNA, Company, GraphNode/Edge, ShortlistItem, Memo, Claim, Event
  store.py         SQLite helpers (runs, events, memory, feedback)
  orchestrator.py  Partner: plan, dispatch, retry, checkpoint
  agents/          reader.py thesis.py market.py mapper.py finder.py analyst.py critic.py
  tools/           web.py (fetch/search, injection guard), modal_client.py, dataset.py
  replay.py        record / replay event logs
```
