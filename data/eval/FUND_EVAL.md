# Fund eval: can Bellwether read a real VC website?

Six funds were run live on 2026-10-15 using Haiku agents. Ground truth for each fund is in `data/eval/<fund>_ground_truth.json`.

**Result: all 6 runs failed.** The dev server hot-reloaded about every 20–40 s while other agents were editing code. Each reload restarted the Reader from the home page. Only point9 produced any output.

| Fund | How the portfolio is served | GT count | Found | Recall | Precision | Thesis (0-5) | Runtime (s) |
|---|---|---|---|---|---|---|---|
| Balderton | WordPress. `/companies/` shows 24 with a JS "Load more"; the full list is on `/status/{live,exited}/page/N/` | 204 | 0 | 0.0% | n/a | 0 | 827 (error) |
| Index Ventures | Static HTML at `/companies/` (330), plus `sitemap-companies.xml` (331) | 331 | 0 | 0.0% | n/a | 1 | >650 (stuck running) |
| Seedcamp | WordPress, all on one page, `/our-companies/` (`.company__item`) | 312 | 0 | 0.0% | n/a | 1 | 824 (error) |
| Point Nine (point9.com is a parked domain) | Webflow `/companies`, 25 per page, `?xxxx_page=N` | 195 | 19 | 8.7% | 89% | 4 | 822 (error) |
| HV Capital | Next.js RSC + Storyblok. The HTML has about 23; the sitemap has 154 `/portfolio/<slug>/` | 154 | 0 | 0.0% | n/a | n/a | 765 (error) |
| First Round | Next.js + Sanity. The HTML has 22; the public GROQ API has 196 | 196 | 0 | 0.0% | n/a | 1 | 822 (error) |
| **Average / total** | | **1392** | **19** | **1.5%** (1.4% pooled) | 89% (1 fund) | **1.4** (5 scored) | **812** (5 finished) |

Team found: 0/6. Deals or memo produced: 0/6.

## Failure patterns, ranked by impact

1. **Hot reload kills runs (6/6 funds).** There were 16–33 "server restarted" recoveries per run. A Reader pass takes 45–90 s, which is longer than the gap between reloads, so no run ever passed step 1.
2. **Checkpoints are too coarse (6/6).** A checkpoint is saved only after the whole Reader step finishes. Each resume re-fetches the home page, and runs that stay "running" loop with no cap on resumes.
3. **The server blocks during runs (5/6).** GET requests took 14–60 s or hung, and the backend was down for more than 60 s while restarting. Page fetches are sync and sequential, and a slow page (blog, `/approach`) blocks the whole step.
4. **Portfolio only partly visible in the HTML (4/6).** Even a clean run would cap recall at about 11–12% for Balderton (24/205), HV (23/154), First Round (22/196) and Point Nine (25/195). The full list sits behind pagination, a sitemap, or a CMS API.
5. **Wrong site or team page (3/6).** point9.com is parked and was treated as unreachable, and it was even cited as a source. Balderton's team page was taken from `/about-balderton/`. Fetch errors during reload were reported as "couldn't be found".
6. **Websites missing or wrong.** For point9, only 37% of the companies found have a website, and Algolia was given algolia.ai.

## Reader fixes (in priority order)

1. **Run evals and demos without `--reload`** (`uv run fastapi run`), or exclude the agent code from the reloader. Cap resumes at 3 per step; after that, finish with partial data or fail cleanly.
2. **Checkpoint each page.** Cache raw HTML per URL in SQLite (`ckpt:<run>:reader:<page>`), along with the resolved final host. On resume, skip pages that are already cached.
3. **Fetch with async and in parallel.** Use httpx with asyncio.gather for home, portfolio, team, about, blog and the sitemap. Set a 10–15 s timeout per page and treat the blog and `/approach` as optional. Keep the API responsive.
4. **Find the full portfolio list before calling the LLM.** Try these in order:
   - Walk `sitemap.xml` and its child sitemaps matching `compan|portfolio|team|person`, and take names from the slugs. This covers Index and HV.
   - Detect the CMS. For Sanity, use a GROQ `*[_type=="company"]` query (First Round). Also check WordPress `wp-json`/taxonomy archives, Webflow `?xxxx_page=N`, `rel=next`, and `__NEXT_DATA__`.
   - Follow pagination until a 404, and compare `total_rows` with the number of rows shown.
   - Warn when the count looks too small next to the fund's stated "500+".
5. **Parse repeated cards with rules, not the LLM.** Find the most common repeated element that has a name and an outbound link (`.company__item`, `type-company`, `company-list-card__name`). Take the name, website, year, sector and description from it. Send only the leftovers to Haiku.
6. **Detect parked domains.** Look for "for sale", "make an offer", or very thin pages. Then search "<name> venture capital", switch to the real domain, and never cite the parked page.
7. **Use a dedicated team source.** Prefer a `/team/` link over an About page, and fall back to the `team_member`/`person`/`team` sitemap slugs.
8. **Report errors honestly.** "Couldn't be found" should only mean a DNS failure or a 404. A timeout or reset is a retry, and a page that returns 200 but is wrong is "wrong site".

**Next step:** once the code is frozen, re-run all 6 funds on a backend with no reload, so recall and thesis can actually be measured.

## After fixes (2026-10-15)

What changed: new `backend/app/tools/portfolio_discovery.py`. It walks the sitemap and its child sitemaps, detects the CMS (Sanity public GROQ API, WordPress wp-json and FacetWP taxonomy archives `/status/<term>/page/N/`, Webflow `?xxxx_page=N`, rel=next, Next.js embedded data), follows pagination, and parses repeated cards with rules. It flags parked domains. Fetches use async httpx (16 at a time, 12 s per page, robots.txt respected). The Reader calls it. Pages and the discovery result are checkpointed per run in SQLite (`page_cache` table, `ckpt:<run>:reader:discovery`). Stage starts are counted, and after 3 resumes the stage uses only cached pages. Point Nine was evaluated on pointnine.com.

**Discovery only** (`discover_full()` called directly, one fund at a time; recall and precision against the ground truth):

| Fund | How found | GT | Found | Recall | Precision | Websites | Runtime (s) |
|---|---|---|---|---|---|---|---|
| Balderton | FacetWP taxonomy archives + cards | 204 | 206 | 99.5% | 99.5% | 147 | 36.5 |
| Index Ventures | sitemap + cards | 331 | 329 | 99.4% | 100% | 119 | 4.4 |
| Seedcamp | repeated cards | 312 | 303 | 97.1% | 100% | 303 | 6.9 |
| Point Nine | Webflow pagination | 195 | 179 | 91.8% | 100% | 179 | 4.6 |
| HV Capital | sitemap | 153 | 153 | 100% | 100% | 1 | 11.1 |
| First Round | Sanity API | 196 | 196 | 100% | 100% | 181 | 11.0 |
| Accel | sitemap + Sanity API | 780 | 778 | 99.7% | 100% | 725 | 31.7 |
| **Total** | | **2171** | **2144** | **98.5%** pooled | ~100% | | **15 avg** |

**Full backend** (port 8010, no reload, DEMO_MODE=live, all 7 started at once; runs were stopped after about 5 min at the coordinator's request). The Reader count is what reached Thesis. The thesis score is 1-5 against the ground-truth thesis. The read time runs from the start of the run to the Reader→Thesis handoff.

| Fund | Reader count | Recall vs GT | Thesis (1-5) | Read time (s) | Note |
|---|---|---|---|---|---|
| Balderton | 37 | ~18% | 4 | 135 | Discovery hit the 90 s Reader timeout under 7× parallel load, so the archives were lost. The timeout is now 180 s |
| Index Ventures | n/a | n/a | n/a | >300 (still reading) | Stuck fetching the portfolio page under load; not finished |
| Seedcamp | 302 | 96.8% | 5 | 136 | |
| Point Nine | 179 | 91.8% | 4 | 98 | Thesis says "AI across digital/physical/bio"; this is the current site copy |
| HV Capital | 153 | 100% | 4 | 136 | Websites mostly missing (not in static HTML) |
| First Round | 195 | 99.5% | 5 | 124 | |
| Accel | 782 | ~100% | n/a (not reached) | 140 | Only 191 websites in this run (discovery timed out; it gets 725 when run alone) |

Compared with before: average recall went from 1.4% to 98.5% (discovery) and 81% (5 finished full runs), and no run restarted from the home page. Still open: (1) discovery runs inside the Reader's 90→180 s budget, and a timeout throws away partial results. It should return what it has. (2) Index's portfolio-page fetch hangs under parallel load (the old `ctx.fetch` path). (3) There's no recheck yet of the 9 Seedcamp cards without links or the 16 older Point Nine companies.
