"""Clean the raw startup sample into the files the Modal model and the backend read.

Input  (read-only, untrusted data): data/raw/startups.csv  (UTF-8 with BOM, 10k rows)
Output:
  data/companies.csv       one row per company, cleaned, with a single `text` field for embedding
  data/investors.json      investor slug -> [{company_id, row_id, date, date_source}], oldest first
  data/investor_index.json investor slug -> {name, aliases, companies, dated_round, dated_any}, plus fund families

Stdlib only, so it runs locally in a second. Run from the repo root:
  python -I -X utf8 ml/prepare.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "startups.csv"
OUT_COMPANIES = ROOT / "data" / "companies.csv"
OUT_INVESTORS = ROOT / "data" / "investors.json"
OUT_INDEX = ROOT / "data" / "investor_index.json"

# Responsible AI: never carry founder personal traits. The raw file has none of these today;
# this guard drops them if a future export adds them.
SENSITIVE_TOKENS = {"gender", "sex", "age", "dob", "birth", "ethnicity", "ethnic", "race", "nationality",
                    "citizenship", "religion", "photo", "headshot", "avatar", "picture", "email", "phone"}

STAGE_LABELS = {"pre-seed": "Pre-seed", "seed": "Seed", "series-a": "Series A", "series-b": "Series B",
                "series-c": "Series C", "growth": "Growth"}
STAGE_ORDER = {k: i for i, k in enumerate(["pre-seed", "seed", "series-a", "series-b", "series-c", "growth"])}

# Rough fixed FX to USD, only for ordering cheque sizes. Not for display as exact money.
FX_TO_USD = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CHF": 1.12, "SEK": 0.095, "TRY": 0.03}

REGIONS = {"europe", "north america", "latam", "asia", "sea", "middle east", "africa", "nordics",
           "benelux", "cee", "dach", "global"}
COUNTRY_LABELS = {"uk": "UK", "us": "US", "uae": "UAE", "sea": "Southeast Asia", "cee": "CEE",
                  "dach": "DACH", "latam": "LatAm"}
SECTOR_LABELS = {"b2b saas": "B2B SaaS", "ai": "AI", "edtech": "Edtech", "proptech": "Proptech",
                 "dev tools": "Dev tools", "web3": "Web3", "insurtech": "Insurtech", "agritech": "Agritech",
                 "deep tech": "Deep tech", "frontier tech": "Frontier tech"}

# Investor-name normalisation ------------------------------------------------------------
LEGAL_SUFFIXES = {"ltd", "limited", "llc", "llp", "lp", "inc", "incorporated", "plc", "pte", "pty", "gmbh",
                  "sa", "sas", "sarl", "ab", "as", "asa", "bv", "nv", "oy", "ag", "kg", "co", "corp",
                  "corporation", "company", "srl", "spa", "sl", "kk", "proprietary", "management",
                  "fund", "i", "ii", "iii", "iv", "v", "vi", "gp", "the"}
GENERIC_WORDS = {"venture", "ventures", "capital", "partners", "group", "holdings", "investments", "angels"}
# Names that are not an investor.
NOT_INVESTORS = {"existing shareholders", "existing investors", "undisclosed", "undisclosed investors",
                 "angel investors", "angels", "others", "various", "n a", "na", "unknown", "private investors"}
# Hand-checked aliases: normalised key -> canonical key.
ALIASES = {
    "local globe": "localglobe",
    "localglobe ventures": "localglobe",
    "index ventures geneva": "index ventures",
    "index ventures uk": "index ventures",
    "accel partners": "accel",
    "accel london": "accel",
    "y combinator continuity": "y combinator",
    "yc": "y combinator",
}
# Fund families (one manager, several vehicles). "Latitude" is LocalGlobe's growth fund, but the
# bare name in round data is ambiguous, so it is kept as its own investor and only grouped here.
FUND_FAMILIES = {"localglobe": ["localglobe", "latitude"]}


def _ascii_fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def investor_key(name: str) -> str:
    s = _ascii_fold(name).casefold().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)          # "(uk)", "(Angel to Venture)"
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    toks = s.split()
    while len(toks) > 1 and toks[-1] in LEGAL_SUFFIXES:
        toks.pop()
    while len(toks) > 1 and toks[0] == "the":
        toks.pop(0)
    key = " ".join(toks)
    if key in GENERIC_WORDS:   # "Venture Corporation" must not collapse into "VENTURE+"
        key = s
    key = key.strip()
    return ALIASES.get(key, key)


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", _ascii_fold(s).casefold()).strip("-")
    return s or "x"


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def to_int(s: str) -> int | None:
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def iso_date(s: str | None) -> str:
    s = clean(s)
    return s[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", s) else ""


def domain_of(url: str) -> str:
    m = re.match(r"^(?:https?://)?(?:www\.)?([^/:?#]+)", url.strip().lower())
    return m.group(1) if m else ""


# Legal-form endings ("LTD", "GmbH", "S.L.", "Kft", "Mbh &co Kg"). Register filings (67% of rows) and EU-grant
# companies (76%) carry them, Y Combinator companies almost never do (2%), so in the embedding text they are a
# fingerprint of where a row came from, not of what the company does. Stripped from the `text` name only.
COMPANY_SUFFIX = re.compile(
    r"[\s,]+(?:ltd|limited|llc|llp|lp|inc|incorporated|plc|pte|pty|gmbh|mbh|ag|kg|co|corp|corporation|sa|sas|sarl|sl|"
    r"slu|srl|spa|bv|nv|ab|as|asa|oy|oyj|kft|lda|ltda|se|gbr|hf|ehf|doo|sro|ou|uab|sia|ug|ev|aps|a/s|s\.?\s?a|"
    r"s\.?\s?l|s\.?\s?r\.?\s?l|b\.?\s?v|n\.?\s?v|&\s?co|anonim sirketi|anonymi etairia)\.?$", re.I)


def text_name(name: str) -> str:
    s = clean(name)
    while True:
        t = COMPANY_SUFFIX.sub("", s).rstrip(" ,.&")
        if t == s or not t:
            return s
        s = t


def build_text(r: dict) -> str:
    """name (legal form removed) + description + summary + problem + business_model + customers + market, de-duplicated."""
    parts, seen = [], set()
    for label, key in [("", "description"), ("", "summary"), ("Problem: ", "problem"),
                       ("Business model: ", "business_model"), ("Customers: ", "customers"),
                       ("Market: ", "market")]:
        v = clean(r.get(key))
        if v and v.casefold() not in seen:
            seen.add(v.casefold())
            parts.append(label + v.rstrip(".") + ".")
    return f"{text_name(r['name'])}. " + " ".join(parts)


def main() -> int:
    with RAW.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        dropped = [c for c in header if set(c.lower().split("_")) & SENSITIVE_TOKENS]
        raw_rows = list(reader)
    print(f"read {len(raw_rows)} rows, {len(header)} columns; dropped sensitive columns: {dropped or 'none present'}")

    variants: dict[str, Counter] = defaultdict(Counter)   # investor key -> raw spellings seen
    links: dict[str, dict[str, tuple]] = defaultdict(dict)  # investor key -> company slug -> (date, source, row_id)
    out_rows, used_slugs = [], set()

    for row_id, r in enumerate(raw_rows, start=1):
        r = {k: v for k, v in r.items() if k not in dropped}
        name = clean(r["name"])
        slug = slugify(name)
        if slug in used_slugs:
            slug = f"{slug}-{r['id']}"
        used_slugs.add(slug)

        try:
            rounds = json.loads(r["funding_rounds_json"]) if r["funding_rounds_json"] else []
        except json.JSONDecodeError:
            rounds = []
        round_dates = [d for d in (iso_date(x.get("announced_on")) for x in rounds) if d]
        headline = iso_date(r["funding_date"])
        all_dates = sorted(set(round_dates + ([headline] if headline else [])))
        first_date, last_date = (all_dates[0], all_dates[-1]) if all_dates else ("", "")
        founded = to_int(r["founded_year"])

        stage = clean(r["funding_stage"]).lower()
        if not stage:
            named = [x.get("round") for x in rounds if x.get("round") in STAGE_ORDER]
            stage = max(named, key=STAGE_ORDER.get) if named else ""

        amount = to_int(r["funding_amount"])
        cur = clean(r["funding_currency"]).upper()
        amount_usd = round(amount * FX_TO_USD[cur]) if amount and cur in FX_TO_USD else None

        # Investors: the company-level list (undated) + the names on each funding round (dated when the round is).
        per_company: dict[str, tuple[str, str]] = {}

        def add(raw_name: str, date: str) -> None:
            raw_name = clean(raw_name)
            if not raw_name:
                return
            key = investor_key(raw_name)
            if not key or key in NOT_INVESTORS:
                return
            variants[key][raw_name] += 1
            prev = per_company.get(key)
            if prev is None or (date and (not prev[0] or date < prev[0])):
                per_company[key] = (date, "round" if date else "")

        for x in rounds:
            d = iso_date(x.get("announced_on"))
            names = list(x.get("investors") or [])
            if x.get("lead_investor"):
                names.append(x["lead_investor"])
            for n in set(names):
                add(n, d)
        for n in (r["investors"].split("; ") if r["investors"] else []):
            add(n, "")
        # Links with no round date fall back to the company's first funding date, then its founding year.
        for key, (d, _src) in list(per_company.items()):
            if not d:
                if first_date:
                    per_company[key] = (first_date, "company_first_funding")
                elif founded:
                    per_company[key] = (f"{founded}-01-01", "founded_year")
        for key, (d, src) in per_company.items():
            links[key][slug] = (d, src, row_id)

        country = clean(r["country"]).lower()
        sector = clean(r["sector"]).lower()
        website = clean(r["website"])
        if website and not website.startswith(("http://", "https://")):
            website = "https://" + website
        out_rows.append({
            "row_id": row_id,
            "id": slug,
            "source_id": r["id"],
            "name": name,
            "website": website,
            "domain": domain_of(website) if website else "",
            "country": country,
            "country_label": COUNTRY_LABELS.get(country, country.title()),
            "country_is_region": int(country in REGIONS),
            "sector": sector,
            "sector_label": SECTOR_LABELS.get(sector, sector.capitalize()) if sector else "",
            "one_liner": clean(r["description"]),
            "summary": clean(r["summary"]),
            "problem": clean(r["problem"]),
            "business_model": clean(r["business_model"]),
            "customers": clean(r["customers"]),
            "market": clean(r["market"]),
            "has_profile": int(bool(clean(r["summary"]) or clean(r["business_model"]))),
            "stage": stage,
            "stage_label": STAGE_LABELS.get(stage, ""),
            # Only the company's own reported stage. `stage` above can come from a round name, e.g. every
            # Y Combinator round is "pre-seed", so it leaks fund membership; the model uses this column instead.
            "stage_reported": clean(r["funding_stage"]).lower(),
            "funding_amount": amount if amount is not None else "",
            "funding_currency": cur,
            "funding_amount_usd": amount_usd if amount_usd is not None else "",
            "funding_date": headline,
            "first_funding_date": first_date,
            "last_funding_date": last_date,
            "n_rounds": len(rounds),
            "founded_year": founded if founded else "",
            "site_status": clean(r["site_status"]),
            "discovery_source": clean(r["discovery_source"]),
            "logo_file": clean(r["logo_file"]),
            "market_scope": clean(r["market_scope"]),
            "market_size": clean(r["market_size"]),
            "market_cagr": clean(r["market_cagr"]),
            "market_year": clean(r["market_year"]),
            "market_source": clean(r["market_source"]),
            "investors": "",        # filled below with canonical display names, '|' joined
            "investor_ids": "",     # matching investor slugs, '|' joined
            "text": build_text(r),
            "_keys": sorted(per_company),
        })

    # Canonical display name = the most common raw spelling (ties: shortest).
    display = {k: sorted(c.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0] for k, c in variants.items()}
    inv_slug: dict[str, str] = {}
    taken: set[str] = set()
    for k in sorted(display):
        s = slugify(k)
        if s in taken:
            s = f"{s}-{len(taken)}"
        taken.add(s)
        inv_slug[k] = s

    for o in out_rows:
        keys = o.pop("_keys")
        o["investors"] = "|".join(display[k] for k in keys)
        o["investor_ids"] = "|".join(inv_slug[k] for k in keys)

    OUT_COMPANIES.parent.mkdir(parents=True, exist_ok=True)
    with OUT_COMPANIES.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    investors, index = {}, {}
    for k, comp in links.items():
        s = inv_slug[k]
        items = [{"company_id": cid, "row_id": rid, "date": d or None, "date_source": src or None}
                 for cid, (d, src, rid) in comp.items()]
        items.sort(key=lambda x: (x["date"] is None, x["date"] or "", x["company_id"]))
        investors[s] = items
        index[s] = {
            "name": display[k],
            "aliases": sorted(variants[k]),
            "companies": len(items),
            "dated_round": sum(1 for x in items if x["date_source"] == "round"),
            "dated_any": sum(1 for x in items if x["date"]),
        }
    investors = dict(sorted(investors.items(), key=lambda kv: (-len(kv[1]), kv[0])))
    index = {s: index[s] for s in investors}
    families = {fam: {"members": [m for m in members if m in index],
                      "companies": sum(index[m]["companies"] for m in members if m in index),
                      "dated_any": sum(index[m]["dated_any"] for m in members if m in index)}
                for fam, members in FUND_FAMILIES.items()}
    OUT_INVESTORS.write_text(json.dumps(investors, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_INDEX.write_text(json.dumps({"investors": index, "fund_families": families},
                                    ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"wrote {OUT_COMPANIES.relative_to(ROOT)} ({len(out_rows)} rows), "
          f"{OUT_INVESTORS.relative_to(ROOT)} ({len(investors)} investors), {OUT_INDEX.relative_to(ROOT)}")
    print(f"{'investor':45s} {'cos':>4s} {'round-dated':>11s} {'any-dated':>9s}")
    for s, meta in list(index.items())[:20]:
        print(f"{meta['name'][:45]:45s} {meta['companies']:4d} {meta['dated_round']:11d} {meta['dated_any']:9d}")
    for fam, meta in families.items():
        print(f"family {fam}: {meta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
