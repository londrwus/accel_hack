# Reader eval: accel.com

Date: 2026-10-15. Model: claude-haiku-5-5 for every role. Ground truth: `data/eval/accel_ground_truth.json`.

## Ground truth (built without the agents)

- **780 portfolio companies.** Source: `sitemap.xml` (780 `/companies/<slug>` pages) joined to Accel's public Sanity CMS, which the site renders from. 748 have a website, 241 have exited.
- **108 team pages**, names only. The CMS has no title field, so the site never labels anyone "Partner".
- **Stated focus**, from the site's own filters: stages Seed/Series A, Early Stage, Late Stage. Regions Americas, Europe & Israel, India & SEA, Oceania. 47 focus tags; the biggest are Cloud/SaaS (328), Consumer (207), Enterprise (161), AI (149) and Fintech (113).
- **How the site is built.** It is a Next.js App Router site that sends its data as an RSC payload (`self.__next_f`); there is no `__NEXT_DATA__`. Almost no visible text is in the HTML: the home page has 154 characters, and `/companies` has 123 characters plus logo links. `/companies` (2.5 MB) carries 200 of the 780 companies, A to C, as embedded JSON with name, website, description and exit status. The other 580 load in the browser only. Search parameters don't change what the server sends. `robots.txt` disallows `/api/`.

## Results

| | Before (`run_accel_20261015_131857_015e`) | After (`run_accel_20261015_133003_ca2f`) |
|---|---|---|
| Portfolio found | 40 | 782 |
| Recall vs 780 | **4.6%** (36) | **99.9%** (779) |
| Precision | 90% | 99.7% (the 2 extra are dataset rows: Billy, Cleo Labs) |
| Companies with a website (for logos) | 3 | 197 |
| Matched to a dataset row (id) | 3 | 18 |
| Team (all correct names) | 20 / 108 | 36 / 108 |
| Stated focus | "The pages read do not state a stage, cheque size or geography" | "Focus on AI, cloud/SaaS, security, consumer, fintech and enterprise, early and late stage, across the Americas, Europe & Israel, India & SEA and Oceania" |
| Run time | 2 m 44 s | 1 m 56 s |
| Tokens (Haiku) | 11 calls, 118k in / 27k out, 8 searches | 12 calls, 99k in / 16k out, 2 searches |
| Rough cost* | ~$0.34 | ~$0.20 (+ ~$0.16 for sector labels, added after this run) |

\*The cost assumes Haiku-class prices of $1 per million input tokens, $5 per million output tokens and $10 per 1,000 searches. Jev was also called about 20 times per run.

**Thesis (after):** "Backs exceptional teams across the Americas, Europe and Israel, India and SEA, and Oceania, with a focus on AI, cloud/SaaS, security, consumer, fintech and enterprise companies." Its themes are AI infrastructure, cloud/SaaS, cybersecurity and identity, consumer and marketplaces, and fintech and payments. This matches the ground truth well. The sector chart was weak, though: only the 18 matched companies had a sector, so it read "Fintech 2". The sector labelling below fixes this, but no live run has measured it yet.

**Top picks (after):** Monday.com 89, FINPACT 88, Driven 88, 24[7].ai 88, ZeroRisk 88, Sponge 88, FintechOS 87, Nomis Solutions 87, Septeo 87, Ningi 87. In the before run the top pick was OpenAI, chosen from a 40-company, AI-heavy view of the portfolio.

**Memo (after):** Monday.com, with 12 claims, all sourced: 5 from web URLs and 7 from dataset rows. The before memo was on OpenAI, with 10 claims (7 web, 3 dataset).

**Map (after):** Celonis, Lovable, Scale, Bird Scooters, Callsign and CareStack, all real Accel companies. The before map included Billy, Cleo Labs and Oak, which come from dataset or name matches of doubtful accuracy.

## What was fixed (backend/app/tools/web.py, backend/app/agents/reader.py, context.py)

1. **Embedded data.** `web.embedded_records()` reads `__NEXT_DATA__`, JSON-LD and the Next.js RSC payload. It returns company records (name, website, description, slug, exit status) and the site's filter menus (stage, region and focus lists). No model is involved, it is free, and it takes under 1 s on 2.5 MB.
2. **Sitemap.** `web.sitemap_urls()` reads robots.txt, sitemap.xml and up to 4 child sitemaps. `web.detail_slugs()` finds every `/companies/<slug>` and `/portfolio/<slug>` page. Companies that render only in the browser are found this way: 780 of 780.
3. **Bigger byte cap for portfolio pages** (8 MB instead of 1.5 MB), so the whole embedded list arrives.
4. **No portfolio in the Haiku prompt when the data already has it.** This saves output tokens. When a portfolio is long and text-only, the extra text is read in up to 4 Haiku chunks in parallel, then deduplicated.
5. **The 120-company cap was raised to 1,500.** Thesis now sees a sample spread across the whole portfolio (`portfolio_sample`) instead of only the first 80, which were all A to C.
6. **Each company keeps its website** even when it matches the dataset, which logos need. Dataset matching is stricter: a name-only match must be in the fund's dataset portfolio or be a distinctive name of 7 or more characters, and it must not contradict the listed website. When a non-dataset company's slug equals a dataset id, it gets a `-portfolio` suffix, so "bird" (Bird messaging) is not mistaken for the dataset's Bird scooters row.
7. **Sector labels for companies without one** (`_label_sectors`, Haiku, chunks of 100 run in parallel). In a direct test on the 782 companies it labelled 666, in 35 s with chunks of 200. Chunks are now 100, which should take about 15 s, but that hasn't been measured. Top labels: B2B SaaS 125, Fintech 86, Dev tools 81, Cybersecurity 66, AI 65, Consumer 58.
8. Team extraction allows up to 40 people (was 20).

## Known gaps

- Only 197 of 780 companies have a website. The other 583 render only in the browser, and the only place to get their website is each company's own page, which is about 2 MB each. That is out of the per-run page budget (30 pages) by design, so these companies show no logo unless they match the dataset.
- Team: 36 of 108. The `/team` page itself renders only part of the team.
- The sector labels were checked in a direct test, not in a full live run, because of the 3-run cap.

Live recordings: `data/cache/replay/live/accel-run_accel_20261015_131857_015e.jsonl` (before) and `data/cache/replay/live/accel-run_accel_20261015_133003_ca2f.jsonl` (after). Neither was promoted.
