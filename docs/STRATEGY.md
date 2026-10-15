# Strategy: how we get scored and how we win

## The rubric

| Criterion | Weight | What judges actually check | Our lever |
|---|---|---|---|
| Real output | 20% | Live link or proof of a run. A working end-to-end run beats a polished mock-up. | One full run, URL → memo, live on stage. A recorded replay is the backup. |
| Agent design & architecture | 15% | Do agents run for a long time or work as a team? Planning, hand-offs, memory, error recovery. | A visible agent team on Research: plan, hand-offs, a "recovered" event, memory across runs, watch mode. |
| Business viability | 20% | Clear customer, real problem | Judges are VCs at Accel. **They are the customer.** Use their own pain in the pitch. |
| Demo & pitch | 15% | Clear story, live demo, show what the agents do in 5 min. Round 1 is explained at the table. | Tight script (`PITCH.md`). Start the run first and talk while it works. |
| Demo clarity | 15% | Easy to follow | 4 screens, plain words, one color per node type, big numbers. |
| Responsible design | 15% | Safety, privacy, misuse | Citations, Critic agent, human approval gate, no protected attributes, prompt-injection guard, shown **in the UI** and not only in a doc. |

About 50% of the score (Real output + Demo & pitch + Demo clarity) depends on what people see. That's why design comes first.

## How we hit each criterion visibly

- **Real output**: the run produces real artifacts from a real URL: fund DNA, a graph, a ranked list and a memo, each with source links. Live, these can be checked by clicking a citation.
- **Agents**: the Research screen shows 6 named agents, who handed work to whom, a plan checklist, and at least one real retry/recovery. Watch mode ("next morning") shows memory: *"Since last run: 2 new companies, 1 portfolio competitor raised."*
- **Business**: one sentence of pain, one number, one customer. "A seed fund sees ~3,000 decks a year with 2 analysts. Bellwether gives each analyst a team that never sleeps." Pricing: a per-seat SaaS (e.g. £1–2k/month per fund). Wedge: small funds and angel syndicates with no analysts.
- **Responsible**: a "Trust" strip on the memo: every claim has a source, Critic checks passed/failed, "Human decision required" buttons, and a note on which data was **not** used (gender, age, ethnicity).

## Honest odds

**Strengths**
- The judges are exactly the target customer. They feel the problem in their own week, and nobody needs it explained to them.
- The output is very visual: a node map plus live agents is a good stage demo.
- It fits the "long-running agents" theme directly: an analyst that keeps running.

**Risks**
- **Crowded space.** Harmonic, Specter, Tracxn, Dealroom, Affinity, EQT Motherbrain, and pitch2.fund (which has a "fund-side scoring" tool) all exist. A VC judge will ask *"how is this different from Harmonic?"*
  - Our answer: *those are databases you search. Bellwether is a team that does the work: it learns your thesis from your URL in 2 minutes with zero setup, writes the diligence, and keeps watching. It's an analyst, not a database.*
- **Hallucinated facts in front of VCs** would kill trust. That's why we have the Critic agent and citations, and why the demo fund must be rehearsed.
- **Live-demo failure.** Network or rate limits. Mitigation: `DEMO_MODE=replay` plus a pre-computed run for the demo fund.
- The "fully autonomous VC" framing can sound like replacing the judges. Pitch it as **"autonomous analyst, human partner"**.

**Estimate.** With a clean live run and a sharp pitch, we can realistically score ~75–85/100 on this rubric and make a top-3 shortlist. Winning outright depends on the field: maybe **20–30%** in a typical field of 20–40 teams. These are the swing factors, in order:
1. The live run works end to end on stage (Real output 20%).
2. The audience understands it in 30 seconds (Clarity + Pitch 30%).
3. We have a crisp answer to "vs Harmonic/Specter".

## Demo fund choice

- **Primary: LocalGlobe** (London seed, public portfolio, local to the judges). Rehearse and pre-cache it.
- **Backup: Haatch** (UK seed B2B, smaller and cleaner portfolio).
- **Optional wow moment:** at the end, ask a judge for *their* fund's URL and start a live run. The agents run in the background while we take questions. Only do this if the live pipeline has been stable in rehearsal.
- Avoid running on Accel itself as the main demo: if the output is wrong, it's wrong about the judges.
