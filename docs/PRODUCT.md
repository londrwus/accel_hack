# Product

## Customer

| Segment | Pain | Why Bellwether fits |
|---|---|---|
| **Seed / Series A funds (primary)** | 1–3 analysts, thousands of inbound and outbound companies | An analyst team that costs a fraction of a hire |
| Angel syndicates / solo GPs | No analyst at all | Instant thesis, shortlist and memo |
| Corporate VC | Need to explain decisions to the parent company | Cited, auditable memos |

The buyer is the managing partner. The user is the analyst or associate.

## Problem

Sourcing and first-pass diligence are slow, manual and repetitive: reading news, searching databases, comparing to the
portfolio, writing memos. Good deals get missed because nobody had time, not because the fund decided against them.

## Core flow (the whole product)

1. **Start**: paste a fund URL (or pick an example fund). Press *Run*.
2. **Research**: watch the agent team work live. The fund DNA fills in.
3. **Market Map**: see the portfolio, competitors and predicted next deals as a node map, next to a ranked shortlist.
4. **Investment Memo**: open the top pick to read the one-page diligence. Approve / Pass / Ask for more.
5. **Watch mode**: Bellwether re-runs on a schedule and shows "what changed since last run".

## In scope (hackathon)

- One fund per run. A fully working demo on 1–2 rehearsed funds plus a live attempt on any URL.
- Shortlist of the top 10 from the 10k dataset, with a full memo for #1 (and others on click, generated on demand).
- Competitor map for portfolio companies and predicted companies.
- Partner feedback (Approve/Pass) stored in memory and used in the next run.
- Simulated "next morning" re-run for the demo.

## Out of scope

User accounts and auth, multi-fund workspaces, CRM integrations, email outreach (deliberately left out, see `RESPONSIBLE_AI.md`),
deep financial modelling, mobile layout beyond basic responsiveness.

## Success metric for the demo

From a cold URL to the first predicted deal on screen in **under 3 minutes**, and a full memo in under 5.
