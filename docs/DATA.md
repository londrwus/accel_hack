# Data & the (simple) ML model

## The 10k company dataset

A 10,000-company sample of the pitch2.fund index (stratified by country, see `data/raw/README.md`).
Raw files live in `data/raw/` (read-only, git-ignored). `ml/prepare.py` cleans them into `data/companies.csv`,
`data/investors.json` and `data/investor_index.json` (all git-ignored). Full column list and fill rates: **`data/SCHEMA.md`**.

Run: `python -I -X utf8 ml/prepare.py` (stdlib only, about a second).

### Column mapping (cleaned `data/companies.csv` → contract `Company`)

| Contract field | Column | Notes |
|---|---|---|
| `id` | `id` | slug from the name, unique |
| `row_id` | `row_id` | 1..10,000 |
| `name`, `website` | `name`, `website` | website 97.5% filled |
| `one_liner` | `one_liner` | raw `description`, always filled |
| `sector` | `sector_label` | 26 sectors, 470 rows empty |
| `stage` | `stage_label` | **only 513 rows (5%) have a stage**; send `"Unknown"` or hide the chip otherwise |
| `country` | `country_label` | 69 values; 12 are regions (`europe`, `dach`, `sea`, ...), flagged by `country_is_region` |
| `city` | none | not in the data, always `null` |
| `founded` | `founded_year` | 77% filled, 2005–2026 |
| `logo` | `logo_file` / `domain` | 80% have a logo file; else the favicon URL from `domain` |
| (embedding) | `text` | name (legal form like Ltd/GmbH removed) + description + summary + problem + business model + customers + market |
| (thesis match) | `investors`, `investor_ids`, `first_funding_date`, `funding_amount_usd` | see below |

### Caveats (say these plainly if asked)
- **Sparse funding data.** Funding amount 13%, any funding date 13%, investors 26%. Most rows come from company registers
  (`us_state_register`, `companies_house`, `asic_au`, ...), so they are young or tiny companies with no rounds.
- **Website profile for 31% only** (`summary`, `problem`, ...). For the rest, `text` is just the name + a ≤200-char one-liner.
- **Market fields are per sector, not per company** (22 distinct "Global X market" values). Don't cite them as company facts.
- **Not all rows are startups.** EU grant participants include corporates (Rolls-Royce plc, Saab). Some countries look wrong
  (Goodlord, a London company, is `us`). Some one-liners are cut short at an apostrophe ("BuuPass is Kenya").
- **Investors column has no dates**; only `funding_rounds_json` rounds do. Round data is dominated by EU grants (1,508 of 2,935 rounds,
  CORDIS) and Y Combinator (288, all undated). Only 2 investors have ≥ 20 dated companies; only 4 have ≥ 10 companies at all.
- **Label leaks for the backtest.** `discovery_source = yc` marks 266 of the 288 YC companies and `cordis_*` marks the EU-grant companies.
  `investors`, `investor_ids` and `discovery_source` must **never** be model features, only labels.
  A subtler one is the **name style**: 67% of register rows and 76% of EU-grant rows end in a legal form ("PTY LTD", "Sl", "GmbH"),
  only 2% of YC rows do. `text` drops that ending, so the embeddings and the keyword baseline can't use it as a source fingerprint.
  The same goes for `stage`: 272 of its 308 `pre-seed` values come from the Y Combinator round itself. The model uses
  `stage_reported` (the company's own `funding_stage`, 229 rows) instead. Funding rounds, amounts and dates are not features either.
- **No founder personal data.** There are no founder gender, age, ethnicity, nationality, photo, email or phone columns
  (checked; `prepare.py` would drop them if a future export added them). `country` is the company's location.

### Fund history in the dataset (from `data/investor_index.json`)

| Investor | Companies | Dated by round | Dated (any) | Usable for a time-ordered backtest? |
|---|---|---|---|---|
| Y Combinator | 288 | 0 | 252 | **Yes, with a proxy date** (`founded_year`, YC invests near founding) |
| European Commission (EU grants) | 250 | 250 | 250 | Yes, real dates, but it is a grant body, not a VC |
| Bangladesh Angels Network | 13 | 0 | 0 | No |
| Cento Ventures | 10 | 0 | 2 | No |
| Bpifrance | 9 | 9 | 9 | No (too few) |
| **LocalGlobe** (+ Latitude) | 1 (+2) | 0 (+2) | 1 (+2) | **No: 3 companies in total** |

**Backtest decision:** run `backtest("y-combinator")` as the headline (hold out the 20 most recently founded of 252 dated YC companies)
and `backtest("european-commission")` as a second check. For `localglobe` write `enough_history: false`, so the Universe page shows
"Not enough history for this fund". LocalGlobe's live scoring still works: `score_fit` takes the portfolio the Reader agent scrapes
from the fund's website, not dataset labels.

## The model (keep it shallow)

Everything heavy runs on **Modal**. The Windows laptop only calls it. Code: `ml/modal_app.py` (Modal wiring) and
`ml/fitcore.py` (the scoring and backtest logic, pure numpy + scikit-learn, shipped into the image).

1. **Embed** (one-off Modal job): embed the `text` column (name, one-liner, website profile) for all 10k rows with `BAAI/bge-base-en-v1.5`.
   Store the vectors in a Modal Volume (a 10k × 768 float32 array is ~30 MB).
2. **`similar_companies(text | company_id, k)`**: cosine similarity. Used by the Mapper (competitors) and for "companies like this".
3. **`score_fit(fund_dna, portfolio, k=50, fund_id=None)`**: a "learned from your portfolio" score, trained per fund on the fly
   (well under a second of scoring on Modal CPU once warm).
   - **Positives** = the fund's portfolio. Each item can be a dataset id, name, website or `#0193`, or a dict
     `{name, website?, one_liner?, sector?, country?, stage?, founded?}`. Items that are in the dataset use their stored vector.
     Items that aren't, but have a description, are embedded on the fly and still count. Bare names we can't find go to `unmatched`.
   - **Negatives** = 3,000 random other rows (fixed seed per fund).
   - **Features** (each about 0..1): `sim_max` (closest portfolio company), `sim_mean` (the portfolio as a whole), `thesis`
     (similarity to the Fund DNA summary + themes), `sector` (portfolio share + DNA share of the company's sector), `stage`
     (stated stages vs `stage_reported`; unknown = 0.5), `geo` (portfolio share of the country + DNA geography match), `recency`.
     Portfolio companies get **leave-one-out** features, so their similarity to themselves is never counted.
   - **Model**: logistic regression with **non-negative weights**, so "more like the portfolio" or "right sector" can only raise a score
     and the explanations never say "being in their sector counts against you". Positives count 1 each and the negatives together count
     as much as the positives. With L2 = 1, a 6-company fund gets a heavily regularised model and a 230-company fund a confident one.
     The weights are also shrunk towards fixed defaults, which count like 10 portfolio companies, so the written thesis and location
     still matter for a small portfolio.
   - **Recency is not learned.** We only know a company's age today, not its age when the fund invested, so a learned weight just learns
     that portfolio companies are older than brand-new register filings. The backtest confirms this (see below). Instead, when the DNA
     says pre-seed/seed, recency gets a small fixed weight.
   - **Fit 0–100**: a company that looks as much like the fund as a typical company it already owns scores **90**. The dataset
     average scores 30. Above 90 the curve bends towards 99.
   - **Per result for the backend**: `fit` (0–99, what the UI shows), `score` (= fit / 100), `logit` (raw ranking value),
     `parts` (`{"Like the portfolio": 0..1, "Right stage": .., "Right location": .., "Right sector": .., "Fits the thesis": ..,
     "Founded recently": ..}`, only parts the model uses; `backend/app/agents/ml.py` reads this first), the same as a contract
     `fit_parts` list, and `like` (the closest portfolio company id).
   - **Contributions** per result: `{feature, part, label, value, raw, impact}`. `label` is plain English ("Very like Cleo",
     "Right sector (Fintech)", "Right location (UK)", "Founded recently (2026)"). `value` is 0..1 for the bar. `impact` is the signed
     push on the score, and results are sorted by it. `part` groups features into the UI bars: Like the portfolio · Fits the thesis ·
     Right sector · Right stage · Right location · Founded recently.
     Plus `nearest_portfolio` (top 3 portfolio companies by similarity).
4. The Deal Finder agent re-ranks the top 50 to the top 10 using Claude and writes the plain-English "why".

The coefficient contributions make the score explainable. That's good for both the demo and the Responsible design criterion.

## Modal app (`ml/modal_app.py`)

> **Status (2026-10-15): written, not deployed.** The Modal workspace `stalkerdestroyerthaw` refuses every deploy with
> "Workspace ... has exceeded its spend limit". The data upload still works (the volume holds the current `companies.csv`,
> `investors.json` and `investor_index.json`; re-uploaded after the 2026-10-15 leakage audit changed `text`), so the only missing
> steps are deploy → `embed_all` → `run_backtests` → `python -I ml/check_deployed.py`. The deploy was retried during the audit and
> still failed the same way. `data/cache/backtest_{localglobe,bpifrance}.json` (`enough_history: false`) are already written,
> because they don't need the model.

```
app: bellwether   volume: bellwether-data (mounted at /data)
  /data/companies.csv, investors.json, investor_index.json   <- ml/upload.py
  /data/embeddings.npy (float32 [10000, 768], L2-normalised), embedding_ids.json, embed_meta.json   <- embed_all()
  /data/cache/backtest_{fund}.json   <- backtest()
image: debian_slim py3.12 + torch 2.7.1 + sentence-transformers 4.1 + numpy + scikit-learn (+ scipy); BAAI/bge-base-en-v1.5
       weights baked in; ml/fitcore.py added as a local module
  embed_all(batch_size=256)                      L4 GPU, embeds `text` for every row
  similar_companies(query, k=10, exclude_ids=None)  CPU; query = free text, a company id, an exact name or a row number ("#0193").
                                                 -> {query, query_company, model, results: [{company_id, id, row_id, name, one_liner,
                                                     sector, sector_key, stage, country, founded, website, domain, score}]}
  score_fit(fund_dna, portfolio, k=50, fund_id=None)  CPU, warm 15 min, timeout 5 min
                                                 -> {fund_id, k, dataset_size, n_scored, model: str, feature_weights[{label, share,
                                                     color}], results: [Company fields + rank, fit, score, logit, parts{}, fit_parts[],
                                                     like, contributions[], nearest_portfolio[]], portfolio: {matched, external,
                                                     unmatched}, thesis_text, model_info: {method, n_positive, n_negative,
                                                     coefficients, feature_weights, fit_note, never_used}, score_seconds}
  backtest(fund)                                 CPU x4, timeout 15 min -> Backtest-shaped dict (+ status, details); also saved
                                                 to /data/cache
Cost: every function scales to zero (no min_containers). similar_companies / score_fit keep a container warm 15 min after the
last call (about $0.03 of idle CPU each) so the demo answers fast; embed_all and backtest shut down after 60 s.
local entrypoints: smoke (similar_companies), smoke_fit (score_fit on an example LocalGlobe portfolio),
                   run_backtests (y-combinator, european-commission, bpifrance, localglobe -> data/cache/backtest_*.json locally)
ml/check_deployed.py: calls the deployed functions exactly like backend/app/modal_client.py (Function.from_name + .remote /
                   .spawn) and validates every answer against backend/app/models.py; --save-backtests writes data/cache.
```

Steps: `python -I ml/upload.py` → `cd ml; modal deploy modal_app.py` → `modal run modal_app.py::embed_all` → `modal run modal_app.py::smoke`
→ `modal run modal_app.py::smoke_fit` → `modal run modal_app.py::run_backtests` → `python -I ml/check_deployed.py` from the repo
root (set `PYTHONUTF8=1` first). The backend calls them
with `modal.Function.from_name("bellwether", name)`. Every return value is plain JSON types (no numpy), so the backend can unpickle it
without numpy. Free-text queries and the thesis get BGE's search prefix ("Represent this sentence for searching relevant passages: ").
Company-to-company lookups use the stored vector.

## Caching

- `data/cache/fund_{slug}.json`: scraped pages + Fund DNA (avoids re-scraping during rehearsals).
- `data/cache/{fund}.jsonl`: the recorded event log for replay mode.

## Backtest (feeds the Startup Universe page)

`backtest(fund)` (logic in `fitcore.run_backtest`; leakage audit 2026-10-15, rules in its docstring):

1. Take the fund's companies that are in the dataset and have a date (`investors.json`). Fewer than **25** dated deals gives
   `enough_history: false` and `status: "not_enough_history"`, so the UI shows "Not enough history for this fund". This is the
   same rule as `backend/app/modal_client.py` (`MIN_DATED_DEALS = 25`, `MIN_HELD_OUT = 10`).
2. Sort by date, with a fixed tie-break (sha1 of the company id). Hold out the last `min(20, max(10, n // 3))`: 20 for YC and
   the European Commission.
3. **Purge:** train only on deals dated **strictly before** the first held-out date. Deals that share that date but weren't held
   out are dropped from training and from the candidates. For YC this drops 10 companies founded in 2025, the same year as
   9 of the held-out ones, so no same-year company teaches the model.
4. Train `score_fit`'s model on those earlier deals only. The thesis text is written from their top sectors and countries and
   never names the fund. The "as of" date is the last training deal.
5. Rank **every company that isn't a training, purged or undated deal of the fund**. Undated deals are left out because we can't tell
   whether they came before or after. Model, keyword and random are scored on exactly the same candidates.
   **Negatives** are a seeded random sample of every row that isn't a training deal, so held-out companies can be drawn as negatives.
   That is correct, because they are unlabelled when the model trains, and it can only hurt the model. `investors`, `investor_ids`,
   `discovery_source`, round data, the round-derived `stage` and the legal-form endings in names are never features. The stage feature
   is leave-one-out, like similarity, sector and location.
6. Report top-1/5/10% hits, recall@10/50/100/500, median rank and a binomial p-value against random for:
   - **Bellwether model**
   - **Keyword search**: the **strongest** of three TF-IDF variants, picked on the held-out companies, which favours the baseline:
     `centroid` (cosine to the training portfolio's average), `max` (best single match) and `plus_structure`. `plus_structure` is
     the same logistic model with the same sector, stage, location and thesis features, but TF-IDF in place of the embeddings, so it
     gets **exactly the same information** and only the text representation differs.
   - **Random pick**: the analytic expectation, `held_out × cutoff / candidates` (that's the exact hypergeometric mean).
   - Extra checks in `details.metrics`: `embedding_only` (rank by `sim_max`), `model_with_learned_recency`, `keyword_variants`, and
     `website_profile_only`. The last ranks only companies with a website profile. Portfolio companies usually have one and register
     filings don't (YC 78%, EC 96%, everyone else 28%), which alone makes them easier to find. **This is the honest number to quote.**
7. Write `/data/cache/backtest_{fund}.json`. `modal run modal_app.py::run_backtests` (or `python -I ml/check_deployed.py
   --save-backtests`) also saves it to the local `data/cache/`, which is the file `GET /api/backtest` reads first. Shape: the `Backtest`
   contract model (`methods` = model / keyword / random at the top 5%, `feature_weights` = the model's standardised weight shares).
   Pydantic ignores the extra keys `status` and `details`.

**Funds:** `y-combinator` is the headline: 252 dated, with founding-year stand-in dates, so the held-out companies are the most
recently founded. `european-commission` has real grant dates, but it is a grant body. `bpifrance` and `localglobe` get
`enough_history: false`: Bpifrance has 9 dated deals, and LocalGlobe has 1, or 3 counting Latitude. Those two files are already in
`data/cache/`, because they don't need the model.

**Status: no real numbers yet.** The Modal workspace refuses to deploy ("exceeded its spend limit"), so BGE has never run, and
`data/cache/backtest_{y-combinator,european-commission}.json` don't exist. Until they do, `GET /api/backtest` returns 404 for those funds.

**Dry run with a stand-in encoder (TF-IDF+SVD in place of BGE, not the real model, never show these).** This run only tests the
code paths and the contract shapes, which pass pydantic. Results after the audit fixes, top-5% hits out of 20:

| Fund | Model | Keyword (variant) | Random | Website-profile-only check |
|---|---|---|---|---|
| YC | 12 | 12 (plus_structure) | 1 | model 6 of 17, keyword 4, random 0.85 |
| EC | 15 | 17 (plus_structure) | 1 | model 10 of 19, keyword 11 |

Before the fixes it was YC 13 vs 10 and EC 15 vs 14. Most of that gap was the baseline not getting the sector and location
features. With a stand-in encoder that is itself TF-IDF, the model and `plus_structure` *should* tie. The real question is whether
BGE beats TF-IDF, and only the Modal run can answer it. If it doesn't, say so on stage: the value is the always-on analyst, the
explanations and the memo, not a secret ranking trick. YC's dates are founding years, so treat its number as "finds YC-like
companies", not as a forecast of deal timing.
