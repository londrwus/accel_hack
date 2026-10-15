# Plan

Times are relative to the hackathon start (H0). Adjust when the real schedule is known.
Principle: **get a thin end-to-end run working first**, then make it look good, then harden the demo.

| Phase | When | Goal | Exit check |
|---|---|---|---|
| 0. Design | H0–H3 | Screens in `accel.pen`, docs agreed | All screens (landing + 5 platform pages) designed and signed off by the team |
| 1. Skeleton | H3–H6 | FastAPI + SSE + Vite/shadcn shell with 6 routes; fake events stream to Research | Clicking Run shows a fake live feed |
| 2. Data + Modal | H3–H8 (parallel) | Load the CSV, embed on Modal, `similar_companies` + `score_fit` callable | Top 10 for a hand-written thesis returns in <5s |
| 3. Agents v1 | H6–H12 | Reader → Thesis → Finder → Analyst on real data, events streaming | One real fund URL produces DNA + shortlist + memo |
| 4. Map + Critic | H12–H16 | Mapper graph in React Flow, Critic claim checks, conflict flags | Market Map renders from a real run |
| 5. Long-running | H16–H19 | Memory, feedback, watch mode / "next morning" diff, visible retries | A re-run shows "what changed" |
| 6. Polish | H19–H22 | Match the design, empty/loading states, plain-language copy pass | A non-technical person understands each screen without help |
| 7. Demo hardening | H22–end | Record replay runs, rehearse the pitch 5×, deploy a live link | 3 clean rehearsals in a row, replay tested offline |

## Work split (suggested, for 3–4 people)

- **A: Frontend**: Vite/shadcn shell, Research feed, React Flow map, memo page.
- **B: Agents**: orchestrator, agents, prompts, schemas, retries, replay.
- **C: Data/ML**: CSV mapping, Modal app, scoring + contributions, competitor similarity.
- **D: Pitch/Product**: script, demo fund research, Responsible design copy, rehearsals; helps A with polish.

## Deployment (for the "live link")

Lightweight, no Docker: the frontend on Vercel/Netlify (static build), the backend on Modal as an ASGI web endpoint
(we already use Modal) or on Render/Railway from the repo. Decide in Phase 1.
