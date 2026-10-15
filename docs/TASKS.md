# Tasks

Legend: `[ ]` todo · `[~]` in progress · `[x]` done. Keep this file current, because it's the team's shared checklist.

## 0. Design & docs
- [x] Context docs (CLAUDE, README, docs/*)
- [x] Screens in `accel.pen`: Landing, Research, Market Map, Investment Memo (Lightfern light style)
- [ ] Team review of the screens; lock copy
- [ ] Pick the demo funds (LocalGlobe primary, Haatch backup) and sanity-check their public portfolio pages

## 1. Skeleton
- [ ] `backend/`: uv project, FastAPI, `/api/runs`, SSE `/events`, Pydantic models, SQLite store
- [ ] `frontend/`: Vite + React + TS + Tailwind + shadcn/ui, routes: `/`, `/deals`, `/portfolio`, `/research`, `/map`, `/memos/:id`, `/universe`
- [ ] Design tokens from `DESIGN.md` into the Tailwind theme
- [ ] Fake event generator so the frontend can work before the agents are ready

## 2. Data & Modal
- [ ] Receive CSV → `data/SCHEMA.md`, column mapping, drop sensitive columns
- [ ] Modal app: `embed_all`, `similar_companies`, `score_fit` (+ contributions), `backtest`
- [ ] `modal_client.py` in the backend with timeouts + a local fallback (precomputed top-k JSON)

## 3. Agents
- [ ] Orchestrator: plan → dispatch → checkpoint → retry → summary
- [ ] Reader (site crawl, portfolio extraction, page cap, robots.txt)
- [ ] Thesis (Fund DNA with evidence)
- [ ] Market (news / search)
- [ ] Deal Finder (score_fit → re-rank top 10 + why + conflict check)
- [ ] Analyst (memo with cited claims)
- [ ] Critic (claim verification, flags)
- [ ] Mapper (portfolio + competitors + predicted → graph JSON)
- [ ] Prompt-injection guard on all fetched content

## 4. Long-running & memory
- [ ] fund_memory + feedback tables
- [ ] Approve/Pass → thesis weight adjustment
- [ ] Watch mode + "Simulate next morning" diff
- [ ] Visible `recovered` events

## 5. Frontend screens
- [ ] Start
- [ ] Deal Flow (ranked table + signal chips)
- [ ] Startup Universe (data table + backtest + feature weights + model card)
- [ ] Portfolio (KPI strip + 4-column board: needs attention / raising soon / doing well / exited)
- [ ] Research (analyst strip, research log, Partner panel)
- [ ] Market Map (React Flow, legend, shortlist panel, node detail)
- [ ] Investment Memo (verdict, score bars, why, risks, questions, sources, Trust strip, Approve/Pass)

## 6. Demo
- [ ] Record replay logs for the demo funds
- [ ] `DEMO_MODE=replay` tested with Wi-Fi off
- [ ] Live link deployed
- [ ] Pitch rehearsed 5× with a timer; Q&A answers practised
- [ ] Backup: screen recording of a full run
