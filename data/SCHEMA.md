# Data schema

Source: the pitch2.fund 10k sample (`data/raw/`, read-only, git-ignored; see `data/raw/README.md`).
Cleaned by `ml/prepare.py` (stdlib only): `python -I -X utf8 ml/prepare.py` from the repo root.

## Raw file: `data/raw/startups.csv`

10,000 rows, 26 columns, UTF-8 with BOM. `id` and `name` are unique. Fill counts are out of 10,000.

| Column | Filled | Notes |
|---|---|---|
| `id` | 10,000 | pitch2.fund internal id (int) |
| `name` | 10,000 | unique (case-insensitive) |
| `website` | 9,755 | 9,694 distinct (a few companies share a domain) |
| `country` | 10,000 | 69 lowercase values. 12 of them are regions, not countries: `europe`, `north america`, `latam`, `asia`, `sea`, `middle east`, `africa`, `nordics`, `benelux`, `cee`, `dach`, `global`. Top: us 3,596 · uk 2,149 · australia 764 · france 538 · singapore 221 · canada 217 |
| `sector` | 9,530 | 26 values. Top: b2b saas 2,215 · consumer 1,452 · healthcare 811 · ai 810 · fintech 764 · marketplace 626 · edtech 365 · deep tech 311 · proptech 270 · gaming 253 |
| `description` | 10,000 | one-liner, max 200 chars, 9,960 distinct |
| `funding_stage` | 229 | `seed` 73 · `series-a` 67 · `pre-seed` 34 · `series-b` 25 · `series-c` 18 · `growth` 12 |
| `funding_amount` | 1,265 | latest headline round, whole currency units |
| `funding_currency` | 1,237 | USD 781 · EUR 421 · GBP 23 · CHF 9 · SEK 2 · TRY 1 |
| `funding_date` | 1,212 | 2014-11-13 to 2026-08-05 |
| `founded_year` | 7,659 | 2005 to 2026 |
| `site_status` | 3,810 | `ok` 2,273 · `none_found` 820 · `unreachable` 434 · `no_site` 283 · empty = not scanned |
| `discovery_source` | 8,342 | 31 values: `us_state_register` 2,373 · `companies_house` 1,993 · `asic_au` 636 · `formd` (SEC Form D) 580 · `sirene_fr` 463 · `techeu_round` 275 · `yc` 266 · `cordis_horizon`/`cordis_h2020` 239 · ... · empty 1,658 = found on an investor's portfolio page |
| `logo_file` | 7,979 | `logos/{id}.png|jpg` |
| `summary` | 3,096 | AI-read from the company website |
| `problem` | 1,799 | " |
| `business_model` | 1,919 | " |
| `customers` | 2,846 | " |
| `market` | 2,918 | " |
| `market_size`, `market_cagr`, `market_year`, `market_scope`, `market_source` | 2,644 | **sector-level** market stats (22 distinct scopes such as "Global fintech market"), not company-specific |
| `investors` | 2,055 | investor names joined with `"; "` (no name contains `;`). 1,874 distinct raw names. **No dates.** |
| `funding_rounds_json` | 1,602 | JSON list of rounds: `round, amount, currency, announced_on, valuation, lead_investor, investors[], source_url`. 2,935 rounds, 2,580 dated (2014-01-01 to 2026-08-05). Round names are mostly empty (2,433); `pre-seed` 326 is almost all Y Combinator. Sources: cordis.europa.eu 1,508 · sec.gov 625 · funding.tech.eu 409 · ycombinator.com 288 |

**Founder personal data: none.** There are no founder gender, age, ethnicity, nationality, photo, email or phone columns.
`prepare.py` still drops any column whose name contains such a word, in case a future export adds one. `country` is the
company's location, not a founder's nationality.

## Cleaned: `data/companies.csv`

One row per company (10,000), UTF-8, no BOM. Column order as below.

| Column | Meaning |
|---|---|
| `row_id` | 1..10,000, the stable row number (`Company.row_id`, shown as `#0193`) |
| `id` | URL slug from the name (`Company.id`), unique (`-{source_id}` added on a clash) |
| `source_id` | the raw pitch2.fund `id` |
| `name`, `website`, `domain` | website gets `https://` if it had no scheme; `domain` drops `www.` |
| `country`, `country_label`, `country_is_region` | raw lowercase value, display label (`UK`, `US`, `Southeast Asia`, `France`), 1 if it is a region |
| `sector`, `sector_label` | raw lowercase value (empty for 470 rows), display label (`B2B SaaS`, `AI`, `Fintech`) |
| `one_liner` | raw `description` (`Company.one_liner`) |
| `summary`, `problem`, `business_model`, `customers`, `market` | website profile fields, whitespace-cleaned |
| `has_profile` | 1 if the website profile exists (3,096 rows) |
| `stage`, `stage_label` | `funding_stage`, or the latest named round when that is empty. 513 rows have a stage; the rest are empty / "" |
| `stage_reported` | raw `funding_stage` only (229 rows). The model uses this, not `stage`: every Y Combinator round is named `pre-seed`, so `stage` leaks YC membership (272 of 308 `pre-seed` values) |
| `funding_amount`, `funding_currency`, `funding_amount_usd` | headline round. USD uses fixed rough FX (EUR 1.08, GBP 1.27, CHF 1.12, SEK 0.095, TRY 0.03): for ordering only |
| `funding_date` | headline round date (ISO) |
| `first_funding_date`, `last_funding_date` | earliest / latest date over all dated rounds plus `funding_date` (1,257 rows have one) |
| `n_rounds` | number of rounds in `funding_rounds_json` |
| `founded_year` | int or empty |
| `site_status`, `discovery_source`, `logo_file` | as raw |
| `market_scope`, `market_size`, `market_cagr`, `market_year`, `market_source` | as raw (sector-level) |
| `investors` | canonical investor display names, `|` joined (2,597 rows have at least one) |
| `investor_ids` | matching investor slugs, `|` joined (keys of `investors.json`) |
| `text` | the embedding text: `name. description. summary. Problem: ... Business model: ... Customers: ... Market: ...`, duplicates removed. The name loses its legal-form ending (Ltd, GmbH, S.L., Kft, ...): register and EU-grant rows carry one and YC rows almost never do, so it would tell the model where a row came from. Median about 79 chars |

## `data/investors.json`

`{investor_slug: [{company_id, row_id, date, date_source}, ...]}`, oldest first (undated last), investors with most companies first.
2,692 investors. The investor list is the union of the company-level `investors` column and every round's `investors` + `lead_investor`.

`date_source` says how good the date is:
- `round`: the date of the earliest dated round that names this investor (best).
- `company_first_funding`: the investor is only in the undated company-level list; we use the company's first known funding date.
- `founded_year`: no funding date at all; we use `{founded_year}-01-01` (a proxy, used for Y Combinator).
- `null`: no date.

## `data/investor_index.json`

`{"investors": {slug: {name, aliases[], companies, dated_round, dated_any}}, "fund_families": {"localglobe": {members, companies, dated_any}}}`.
`aliases` lists every raw spelling merged into the slug. A fund family groups vehicles of one manager (LocalGlobe + Latitude).

### Investor-name normalisation
ASCII-fold, lowercase, `&` → `and`, drop text in brackets, drop punctuation, then strip trailing legal/fund words
(`Ltd, Limited, LLC, LLP, LP, Inc, Pte, Pty, GmbH, SA, SAS, AB, AS, BV, Corp, Management, Fund, I/II/III ...`) and a leading `the`,
unless that leaves a single generic word (`Ventures`, `Capital`, ...). Plus a short hand-checked alias list (`Local Globe` → LocalGlobe,
`Index Ventures Geneva` / `Index Ventures (uk) LLP` → Index Ventures, `Accel fund` → Accel). Placeholders such as
`existing shareholders` are dropped. 1,874 + 1,043 raw spellings collapse to 2,692 investors.
