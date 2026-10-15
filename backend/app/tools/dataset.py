"""Read rows from the ~10k company dataset (data/companies.csv) and the investor index.

Light on purpose (stdlib csv, loaded once, a few MB). Used by the agents as the `read_dataset` tool and as
the local fallback when the Modal model doesn't answer:

    rows()                        all rows (plain dicts, whitelisted columns only)
    get(company_id | row_id)      one row
    find(name=..., domain=...)    match a company seen on a fund website
    search(q, k)                  keyword search over name + description
    fund_portfolio(fund_id, name) companies the investor index says this fund backed
    similar(row|text, k)          "companies like this" by word overlap (fallback for Modal similar_companies)
    score(dna, portfolio, k)      fit 0..100 with three explainable parts (fallback for Modal score_fit)

Founder gender, age, ethnicity, nationality and photos are never read (data/SCHEMA.md: the file has none,
and only the columns below are loaded anyway).
"""

from __future__ import annotations

import csv
import json
import math
import re
from datetime import date
from functools import lru_cache
from typing import Any, Iterable, Optional

from .. import config
from ..models import Company

_COLUMNS = ("row_id", "id", "name", "website", "domain", "country_label", "country_is_region",
            "sector_label", "one_liner", "summary", "stage_label", "funding_amount", "funding_currency",
            "funding_date", "first_funding_date", "last_funding_date", "n_rounds", "founded_year",
            "investors", "investor_ids", "text")

_STOP = set("""a an and are as at be by for from has have in into is it its of on or our that the their this
to we with your you they them who which while will can more most new over per than up via all also not no
platform company companies startup startups app apps based help helps helping using use users user
software solution solutions service services provider tool tools technology tech data business businesses
""".split())

EUROPE = {"UK", "Ireland", "France", "Germany", "Spain", "Italy", "Portugal", "Netherlands", "Belgium",
          "Luxembourg", "Switzerland", "Austria", "Sweden", "Norway", "Denmark", "Finland", "Iceland",
          "Estonia", "Latvia", "Lithuania", "Poland", "Czechia", "Czech Republic", "Slovakia", "Hungary",
          "Romania", "Bulgaria", "Greece", "Croatia", "Slovenia", "Serbia", "Ukraine", "Cyprus", "Malta",
          "Europe", "Nordics", "Benelux", "CEE", "DACH"}


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9+-]{2,}", (text or "").lower()) if w not in _STOP}


def _int(v: Any) -> Optional[int]:
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def rows() -> tuple[dict, ...]:
    """Every company row as a small dict. Empty when the CSV isn't there."""
    path = config.companies_csv()
    if not path.exists():
        return ()
    out: list[dict] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for i, rec in enumerate(csv.DictReader(f), start=1):
            r = {c: (rec.get(c) or "").strip() for c in _COLUMNS}
            if not r["name"]:
                continue
            r["row_id"] = _int(r["row_id"]) or i
            r["id"] = r["id"] or f"company-{r['row_id']}"
            r["founded_year"] = _int(r["founded_year"])
            r["investor_ids"] = [x for x in r["investor_ids"].split("|") if x]
            r["summary"] = r["summary"][:400]
            r["text"] = r["text"][:512]
            r["_tokens"] = frozenset(tokens(r["text"] or f"{r['name']} {r['one_liner']}"))
            out.append(r)
    return tuple(out)


@lru_cache(maxsize=1)
def _index() -> dict[str, dict]:
    by_id, by_row, by_name, by_domain = {}, {}, {}, {}
    for r in rows():
        by_id[r["id"]] = r
        by_row[r["row_id"]] = r
        by_name.setdefault(_norm_name(r["name"]), r)
        if r["domain"]:
            by_domain.setdefault(r["domain"].lower(), r)
    return {"id": by_id, "row": by_row, "name": by_name, "domain": by_domain}


def size() -> int:
    return len(rows())


def _norm_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    n = re.sub(r"\b(inc|ltd|limited|llc|plc|gmbh|sas|bv|corp|co|the|ai|hq|app)\b", " ", n)
    return " ".join(n.split())


def get(key: str | int) -> Optional[dict]:
    idx = _index()
    if isinstance(key, int) or (isinstance(key, str) and key.lstrip("#").isdigit()):
        return idx["row"].get(int(str(key).lstrip("#")))
    return idx["id"].get(key)


def find(name: str | None = None, domain: str | None = None) -> Optional[dict]:
    idx = _index()
    if domain:
        d = domain.lower().removeprefix("www.")
        if d in idx["domain"]:
            return idx["domain"][d]
    if name:
        return idx["name"].get(_norm_name(name))
    return None


def search(q: str, k: int = 10) -> list[dict]:
    needle = q.lower().strip()
    if not needle:
        return []
    hits = [r for r in rows() if needle in r["name"].lower() or needle in r["one_liner"].lower()]
    return hits[:k]


def company(r: dict) -> Company:
    domain = r.get("domain") or None
    return Company(
        id=r["id"], row_id=r["row_id"], name=r["name"], one_liner=(r["one_liner"] or r["summary"] or "")[:200],
        sector=r["sector_label"] or "Other", stage=r["stage_label"] or "Unknown",
        country=r["country_label"] or None, city=None, founded=r["founded_year"], website=domain,
        logo=f"https://www.google.com/s2/favicons?domain={domain}&sz=128" if domain else None)


def brief(r: dict) -> dict:
    """What an agent sees about a row (short, no personal data)."""
    return {"company_id": r["id"], "row_id": r["row_id"], "name": r["name"], "one_liner": r["one_liner"][:200],
            "summary": r["summary"][:300] or None, "sector": r["sector_label"] or None,
            "country": r["country_label"] or None, "stage": r["stage_label"] or None,
            "founded": r["founded_year"], "last_funding": r["last_funding_date"] or None,
            "website": r["domain"] or None}


# ---------------------------------------------------------------------------
# Investor index -> what a fund already backed
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _investor_files() -> tuple[dict, dict]:
    try:
        index = json.loads((config.DATA_DIR / "investor_index.json").read_text(encoding="utf-8"))
        holdings = json.loads((config.DATA_DIR / "investors.json").read_text(encoding="utf-8"))
        return index, holdings
    except (OSError, ValueError):
        return {"investors": {}, "fund_families": {}}, {}


def investor_slugs(fund_id: str, fund_name: str | None = None) -> list[str]:
    index, _ = _investor_files()
    fam = index.get("fund_families", {}).get(fund_id)
    if fam:
        return list(fam.get("members") or [fund_id])
    wanted = {_norm_name(fund_id.replace("-", " "))}
    if fund_name:
        wanted.add(_norm_name(fund_name))
    found = []
    for slug, info in index.get("investors", {}).items():
        names = {_norm_name(info.get("name", ""))} | {_norm_name(a) for a in info.get("aliases", [])}
        if slug == fund_id or names & wanted:
            found.append(slug)
    return found


def fund_portfolio(fund_id: str, fund_name: str | None = None) -> list[dict]:
    """Rows of companies the dataset says this fund invested in."""
    _, holdings = _investor_files()
    out, seen = [], set()
    for slug in investor_slugs(fund_id, fund_name):
        for h in holdings.get(slug, []):
            r = get(h.get("company_id") or "") or (get(h["row_id"]) if h.get("row_id") else None)
            if r and r["id"] not in seen:
                seen.add(r["id"])
                out.append(r)
    return out


# ---------------------------------------------------------------------------
# Local fallbacks for the Modal model (simple, explainable, fast: ~10k rows in well under a second)
# ---------------------------------------------------------------------------


def _overlap(a: frozenset | set, b: frozenset | set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def similar(query: dict | str, k: int = 10, exclude: Iterable[str] = ()) -> list[tuple[dict, float]]:
    """Companies like `query` (a row or free text), by word overlap, with a small same-sector bonus."""
    skip = set(exclude)
    if isinstance(query, dict):
        q_tokens, q_sector = query["_tokens"], query["sector_label"]
        skip.add(query["id"])
    else:
        q_tokens, q_sector = frozenset(tokens(query)), ""
    scored = []
    for r in rows():
        if r["id"] in skip:
            continue
        s = _overlap(q_tokens, r["_tokens"])
        if q_sector and r["sector_label"] == q_sector:
            s += 0.15
        if s > 0:
            scored.append((r, round(min(1.0, s), 4)))
    scored.sort(key=lambda t: -t[1])
    return scored[:k]


def _geo_match(country: str, geo: str) -> float:
    if not country:
        return 0.4
    g = geo.lower()
    if country.lower() in g:
        return 1.0
    if country in EUROPE and ("europe" in g or "eu" in g.split()):
        return 0.85
    if country == "US" and ("us" in g.split() or "america" in g or "united states" in g):
        return 1.0
    if "global" in g or "anywhere" in g:
        return 0.7
    return 0.15


def _stage_match(stage: str, wanted: str, last_funding: str) -> float:
    w = wanted.lower()
    s = (stage or "").lower()
    if s:
        if s in w or s.replace("-", " ") in w.replace("-", " "):
            return 1.0
        early = {"pre-seed", "seed"}
        if s in early and any(e in w for e in early):
            return 0.8
        return 0.25
    # No stage in the data: young companies with no or recent funding look early-stage.
    return 0.55 if not last_funding else 0.5


def sector_labels() -> list[str]:
    """The dataset's sector names, most common first (so agents use the same words)."""
    counts: dict[str, int] = {}
    for r in rows():
        if r["sector_label"]:
            counts[r["sector_label"]] = counts.get(r["sector_label"], 0) + 1
    return sorted(counts, key=lambda s: -counts[s])


def _same_sector(a: str, b: str) -> bool:
    """'Health' ~ 'Healthcare', 'Deep tech' ~ 'Deeptech', 'B2B SaaS' ~ 'SaaS'."""
    a, b = re.sub(r"[^a-z0-9]", "", a.lower()), re.sub(r"[^a-z0-9]", "", b.lower())
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a) or a in b or b in a))


def _sector_share(sector: str, shares: dict[str, float]) -> float:
    return max((v for name, v in shares.items() if _same_sector(sector, name)), default=0.0)


def score(dna: dict, portfolio_rows: list[dict], k: int = 50, *, sector_weights: dict[str, float] | None = None,
          exclude: Iterable[str] = ()) -> tuple[list[dict], dict[int, int]]:
    """Fit of every row with this fund. Returns (top-k candidates, {row_id: fit} for all rows).

    Each candidate: {"row": row, "fit": 0..100, "parts": {"Like the portfolio": .., "Right stage": ..,
    "Right location": ..}, "like": portfolio row it looks most like or None}.
    """
    skip = set(exclude) | {r["id"] for r in portfolio_rows}
    sectors = {s["name"].lower(): float(s.get("share") or 0) for s in dna.get("sectors", [])}
    thesis_tokens = frozenset(tokens(" ".join([dna.get("summary", ""), " ".join(dna.get("themes", [])),
                                                " ".join(sectors)])))
    port_tokens = [(p, p["_tokens"]) for p in portfolio_rows if p["_tokens"]]
    weights = {k_.split(":", 1)[-1]: v for k_, v in (sector_weights or {}).items() if k_.startswith("sector:")}
    this_year = date.today().year
    all_scores: dict[int, int] = {}
    cands: list[dict] = []
    share_cache: dict[str, float] = {}
    weight_cache: dict[str, float] = {}
    for r in rows():
        if r["id"] in skip:
            continue
        sector = r["sector_label"] or ""
        if sector not in share_cache:
            share_cache[sector] = _sector_share(sector, sectors)
            weight_cache[sector] = sum(v for name, v in weights.items() if _same_sector(sector, name))
        theme = _overlap(thesis_tokens, r["_tokens"])
        best, like = 0.0, None
        for p, pt in port_tokens:
            s = _overlap(pt, r["_tokens"])
            if s > best:
                best, like = s, p
        sector_fit = min(1.0, share_cache[sector] * 2.5)
        like_part = min(1.0, 0.45 * sector_fit + 0.35 * min(1.0, theme * 2.2) + 0.45 * min(1.0, best * 2.0))
        stage_part = _stage_match(r["stage_label"], dna.get("stage", ""), r["last_funding_date"])
        geo_part = _geo_match(r["country_label"], dna.get("geo", ""))
        recency = 1.0 if (r["founded_year"] or 0) >= this_year - 4 else 0.6 if r["founded_year"] else 0.7
        raw = 0.55 * like_part + 0.18 * stage_part + 0.20 * geo_part + 0.07 * recency
        raw += weight_cache[sector] * 0.5  # human feedback nudges (approve/pass)
        fit = max(0, min(99, round(raw * 100)))
        all_scores[r["row_id"]] = fit
        cands.append({"row": r, "fit": fit, "like": like if best >= 0.12 else None,
                      "parts": {"Like the portfolio": round(like_part, 2), "Right stage": round(stage_part, 2),
                                "Right location": round(geo_part, 2)}})
    cands.sort(key=lambda c: (-c["fit"], c["row"]["row_id"]))
    return cands[:k], all_scores
