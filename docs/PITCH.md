# Pitch & demo script

Rule: anyone in the room, including a non-technical guest, should be able to repeat what Bellwether does after hearing it once.

## One-liners

- **What:** Bellwether is an AI analyst team for venture funds. Give it a fund's website, and it finds the fund's next deals and writes the due diligence.
- **Why now:** agents can now work for hours, use tools, and check each other's work. An analyst's job is exactly that kind of loop.
- **Category line (landing header):** *The first systematic VC operating system.*
- **Tagline:** *The first systematic VC analyst. It never sleeps. You make the call.*

Words to avoid on stage: embeddings, vectors, RAG, orchestration, LLM. Say instead: "it reads", "it compares", "it checks its own work", "it remembers".

## 5-minute stage version

| Time | Screen | Say (roughly) |
|---|---|---|
| 0:00–0:30 | Start | "A seed fund sees about 3,000 startups a year and backs 10. Two analysts can't read them all, so great deals get missed. We built Bellwether: give it a fund's website and an AI analyst team gets to work." **Paste the LocalGlobe URL and press Run.** |
| 0:30–1:30 | Research | "These are eight agents, each with one job. The Reader is on their website now, and the Thesis agent is writing down what they invest in. Watch: it just handed the portfolio to the Mapper." Point at the fund DNA card filling in. Point at the **recovered** event: "a site blocked us, so it retried another way. Nobody had to help it." |
| 1:30–2:45 | Market Map | "Every dot is a company. Blue dots are what LocalGlobe already owns, grey dots are their competitors, and the **orange dots are what Bellwether thinks they should look at next**. It compared 10,000 startups against what this fund likes." Click an orange node, and the "why" appears in plain English. |
| 2:45–3:45 | Investment Memo | "For the top pick it wrote a one-page memo: why it fits, risks, and questions to ask the founder. Every sentence has a source you can click. A second agent, the Critic, checked the memo and flagged one claim it couldn't verify." Point at the Trust strip. "And Bellwether doesn't decide. A partner presses Approve or Pass, and Bellwether learns from that." |
| 3:45–4:30 | Research → Watch | "Bellwether keeps running. Here's the next morning: 2 new companies match, and a competitor of their portfolio company just raised. That's an analyst that never sleeps." |
| 4:30–5:00 | Close | "Who pays: seed funds, angel syndicates and corporate VC teams, about £1–2k a month per fund. That's cheaper than one analyst-week. We'd love to run it on your fund: give us your URL." |

## Table version (round 1, ~90 seconds, laptop open)

1. "What does your analyst do on a Monday?" Let them answer.
2. "Bellwether does that every morning, by itself." Run it on the demo fund (or replay).
3. Show the Market Map: "blue is what they own, orange is what they should look at next."
4. Show the memo: "every line has a source, a second agent checks it, and you approve."
5. "Want to try your fund?"

## Proof moment (Startup Universe page, ~20s, use if a judge doubts the model)
"Here are all 10,000 startups in the system. We hid LocalGlobe's last 20 deals from the model, and it found [N] of them in its top 5%.
Random picking finds about 1." Only use the real backtest number.

## Likely questions → answers

- **"How is this different from Harmonic / Specter?"** They're databases you search. Bellwether is a team that does the work: it learns *your* thesis from your URL with zero setup, writes the diligence, and keeps watching. Bellwether could even use those databases as tools.
- **"What if it hallucinates?"** Every claim is cited. A Critic agent checks the memo before you see it, and unverified claims are marked. Nothing happens without a human approving it.
- **"Where does the data come from?"** Public web pages, news, and a dataset of 10k startups. No private data, no scraping of personal profiles.
- **"Bias?"** We never use founder gender, age or ethnicity. We show the geography and sector mix of the shortlist so a partner can spot a skew.
- **"How long does it run?"** The first run takes a few minutes. After that it runs continuously in watch mode, and each re-run only looks at what changed.
- **"Business model?"** SaaS per fund seat. The wedge is small funds with no analysts. Later: LP reporting, portfolio monitoring.

## Roles on the team (fill in)

- Speaker: …
- Driver (clicks the demo): …
- Backup person who restarts in replay mode if anything breaks: …
