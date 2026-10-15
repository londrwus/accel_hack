"""Data layer for the page endpoints.

Order of precedence for every page:
  1. results a run saved for this fund (SQLite `memory`, key `page:<name>`), see `save_page()`
  2. the demo mocks in frontend/src/mocks/*.json (they belong to the demo fund, LocalGlobe)
  3. otherwise `NoData` (the API turns it into a plain-English 404)

The Startup Universe reads `data/companies.csv` with the stdlib csv module when it exists,
otherwise the mock page. Founder traits are never read: only whitelisted columns are loaded.
"""

from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from typing import Any, Optional, TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel

from . import config, store
from .models import (
    Backtest,
    Company,
    DealCounts,
    DealFlowItem,
    DealsResponse,
    Fund,
    FundRef,
    FundResponse,
    MapResponse,
    Memo,
    MemosResponse,
    MemoSummary,
    PortfolioResponse,
    RunState,
    FundSummary,
    UniverseOptions,
    UniverseResponse,
    UniverseRow,
    WatchStatus,
)

T = TypeVar("T", bound=BaseModel)


class NoData(Exception):
    """Raised when there's nothing to show yet. The message is plain English."""


# ---------------------------------------------------------------------------
# Mocks (validated once against the Pydantic contract)
# ---------------------------------------------------------------------------

_MOCK_MODELS: dict[str, type[BaseModel]] = {
    "fund": FundResponse,
    "deals": DealsResponse,
    "portfolio": PortfolioResponse,
    "map": MapResponse,
    "memos": MemosResponse,
    "memo": Memo,
    "universe": UniverseResponse,
    "backtest": Backtest,
    "run": RunState,
}


@lru_cache(maxsize=None)
def mock(name: str) -> Any:
    """Load and validate frontend/src/mocks/<name>.json. Returns a Pydantic model."""
    path = config.MOCKS_DIR / f"{name}.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _MOCK_MODELS[name].model_validate(raw)


@lru_cache(maxsize=None)
def mock_events() -> list[dict]:
    """The recorded demo run (research_events.json), as plain dicts."""
    path = config.MOCKS_DIR / "research_events.json"
    return json.loads(path.read_text(encoding="utf-8"))


def demo_fund_id() -> str:
    return mock("fund").fund.id


def _copy(model: T) -> T:
    return model.model_copy(deep=True)


# ---------------------------------------------------------------------------
# Run results override mocks
# ---------------------------------------------------------------------------


def save_page(fund_id: str, name: str, model: BaseModel) -> None:
    """Called by live agents: store a page result (deals, portfolio, map, fund, universe_scores...)."""
    store.set_memory(fund_id, f"page:{name}", model.model_dump(mode="json"))


def save_memo(fund_id: str, memo: Memo) -> None:
    store.set_memory(fund_id, f"memo:{memo.id}", memo.model_dump(mode="json"))


def save_scores(fund_id: str, scores: dict[int, int]) -> None:
    """row_id -> fit (0..100), shown in the Startup Universe `fit` column."""
    store.set_memory(fund_id, "scores", {str(k): int(v) for k, v in scores.items()})


def _page(fund_id: str, name: str, model: type[T]) -> T:
    saved = store.get_memory(fund_id, f"page:{name}")
    if saved is not None:
        return model.model_validate(saved)
    if fund_id == demo_fund_id():
        return _copy(mock(name))
    raise NoData(f"Nothing for this fund yet. Start a run to fill this page.")


# ---------------------------------------------------------------------------
# Funds
# ---------------------------------------------------------------------------


def fund_id_from_url(url: str) -> str:
    """https://www.localglobe.vc/portfolio -> localglobe"""
    u = url.strip()
    if "://" not in u:
        u = "https://" + u
    host = (urlparse(u).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    label = host.split(".")[0] if host else ""
    return slugify(label) or "fund"


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def get_fund(fund_id: str, url: str | None = None) -> Fund:
    saved = store.get_memory(fund_id, "page:fund")
    if saved is not None:
        return Fund.model_validate(saved)
    if fund_id == demo_fund_id():
        return _copy(mock("fund").fund)
    run = store.latest_run(fund_id)
    url = url or (run["fund_url"] if run else f"https://{fund_id}.com")
    return Fund(id=fund_id, name=fund_id.replace("-", " ").title(), url=url, logo=None, dna=None)


def covered_funds(current: str) -> list[FundRef]:
    refs: dict[str, FundRef] = {r.id: r for r in mock("fund").covered_funds}
    for run in store.list_runs(limit=200):
        if run["fund_id"] not in refs:
            f = get_fund(run["fund_id"], run["fund_url"])
            refs[f.id] = FundRef(id=f.id, name=f.name)
    if current not in refs:
        f = get_fund(current)
        refs[current] = FundRef(id=f.id, name=f.name)
    return list(refs.values())


def fund_initials(name: str) -> str:
    """"LocalGlobe" -> "LG", "Haatch" -> "HA"."""
    caps = re.findall(r"[A-Z]", name)
    return "".join(caps)[:3] if len(caps) >= 2 else (name[:2].upper() or "F")


def list_funds() -> list[FundSummary]:
    """GET /api/funds: the demo fund, the funds you cover, every fund with a run or saved results.
    Demo fund first, then the most recently run."""
    with_results = store.funds_with_results()
    latest: dict[str, dict] = {}
    for run in store.list_runs(limit=500):  # newest first
        latest.setdefault(run["fund_id"], run)
    demo = demo_fund_id()
    ids = [demo] + [r.id for r in mock("fund").covered_funds]
    ids += sorted(latest, key=lambda f: latest[f]["started_at"] or "", reverse=True)
    ids += sorted(with_results)
    out: list[FundSummary] = []
    for fid in dict.fromkeys(ids):
        run = latest.get(fid)
        f = get_fund(fid, run["fund_url"] if run else None)
        out.append(FundSummary(id=f.id, name=f.name, url=f.url, logo=f.logo, initials=fund_initials(f.name),
                               latest_run_id=run["id"] if run else None,
                               last_run_at=run["started_at"] if run else None,
                               has_results=fid == demo or fid in with_results))
    return out


def mock_watch(fund_id: str) -> Optional[WatchStatus]:
    return _copy(mock("fund").watch) if fund_id == demo_fund_id() else None


# ---------------------------------------------------------------------------
# Deals (with human decisions applied)
# ---------------------------------------------------------------------------

_VERDICT_TO_STATUS = {"pass": "passed", "meeting": "under_review", "dig_deeper": "under_review"}


def deals(fund_id: str, status: str | None = None, sector: str | None = None,
          sort: str | None = "fit") -> DealsResponse:
    resp = _page(fund_id, "deals", DealsResponse)
    decisions = store.latest_decisions(fund_id)
    counts = resp.counts.model_dump()
    for item in resp.items:
        verdict = decisions.get(item.company.id)
        new_status = _VERDICT_TO_STATUS.get(verdict or "")
        if new_status and new_status != item.status:
            counts[item.status] = max(0, counts[item.status] - 1)
            counts[new_status] += 1
            item.status = new_status  # type: ignore[assignment]
    resp.counts = DealCounts(**counts)
    items = resp.items
    if status:
        items = [i for i in items if i.status == status]
    if sector:
        items = [i for i in items if i.company.sector.lower() == sector.lower()]
    if (sort or "fit") == "fit":
        items = sorted(items, key=lambda i: (-i.fit, i.rank))
    resp.items = items
    return resp


def portfolio(fund_id: str) -> PortfolioResponse:
    page = _page(fund_id, "portfolio", PortfolioResponse)
    if not any(col.rest for col in page.columns) and any(col.more for col in page.columns):
        _fill_rest(fund_id, page)  # pages saved before columns kept their hidden companies
    enr = enrichments(fund_id)
    if enr:
        for col in page.columns:
            for it in col.items + col.rest:
                apply_enrichment(it.company, enr.get(it.company.id))
    return page


def _latest_read(fund_id: str) -> Optional[dict]:
    reads = {k: v for k, v in store.list_memory(fund_id, "ckpt:").items() if k.endswith(":read")}
    return reads[max(reads)] if reads else None


def _fill_rest(fund_id: str, page: PortfolioResponse) -> None:
    from .models import PortfolioItem
    rd = _latest_read(fund_id)
    if not rd:
        return
    shown = {it.company.id for col in page.columns for it in col.items}
    cols = {col.health: col for col in page.columns}
    for p in rd.get("portfolio", []):
        try:
            c = Company.model_validate(p["company"])
        except Exception:
            continue
        if c.id in shown:
            continue
        shown.add(c.id)
        col = cols.get("exited" if p.get("exited") else "good")
        if col is not None:
            col.rest.append(PortfolioItem(company=c, health=col.health, signals=[]))
    for col in page.columns:
        col.rest.sort(key=lambda i: i.company.name.lower())
        col.count = len(col.items) + len(col.rest)
        col.more = len(col.rest)


# ---------------------------------------------------------------------------
# Enriched profiles (app.agents.enricher), merged over what the pages know
# ---------------------------------------------------------------------------

_PLACEHOLDER = {"", "unknown", "n/a", "not public", "other"}


def enrichments(fund_id: str) -> dict[str, dict]:
    return {k.split(":", 1)[1]: v for k, v in store.list_memory(fund_id, "enrich:").items()}


def enrichment(fund_id: str, company_id: str) -> Optional[dict]:
    return store.get_memory(fund_id, f"enrich:{company_id}")


def apply_enrichment(c: Company, e: Optional[dict]) -> Company:
    """Fill empty fields of `c` in place from an enriched profile."""
    if not e:
        return c
    for f in ("one_liner", "sector", "stage", "country", "founded", "website"):
        cur = getattr(c, f, None)
        if e.get(f) and (cur is None or str(cur).strip().lower() in _PLACEHOLDER):
            setattr(c, f, e[f])
    return c


def market_map(fund_id: str) -> MapResponse:
    return _page(fund_id, "map", MapResponse)


# ---------------------------------------------------------------------------
# Memos
# ---------------------------------------------------------------------------


def _all_memos(fund_id: str) -> dict[str, Memo]:
    memos: dict[str, Memo] = {}
    if fund_id == demo_fund_id():
        m = _copy(mock("memo"))
        memos[m.id] = m
    for key, value in store.list_memory(fund_id, "memo:").items():
        m = Memo.model_validate(value)
        memos[m.id] = m
    decisions = store.latest_decisions(fund_id)
    for m in memos.values():
        if m.company.id in decisions:
            m.decision = decisions[m.company.id]  # type: ignore[assignment]
    return memos


def memo(fund_id: str, memo_id: str) -> Optional[Memo]:
    return _all_memos(fund_id).get(memo_id)


def memos(fund_id: str) -> MemosResponse:
    found = _all_memos(fund_id)
    if not found and fund_id != demo_fund_id():
        return MemosResponse(items=[])
    items = [MemoSummary(id=m.id, company=m.company, title=m.title, fit=m.fit,
                         created_at=m.created_at, decision=m.decision) for m in found.values()]
    items.sort(key=lambda s: s.created_at, reverse=True)
    return MemosResponse(items=items)


# ---------------------------------------------------------------------------
# Backtest: only the file the Modal job writes. Never the mock numbers.
# ---------------------------------------------------------------------------


def backtest(fund_id: str) -> Optional[Backtest]:
    path = config.CACHE_DIR / f"backtest_{fund_id}.json"
    if not path.exists():
        return None
    return Backtest.model_validate(json.loads(path.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Startup Universe (CSV, paged with stdlib csv; or the mock)
# ---------------------------------------------------------------------------

# Whitelisted columns only. Founder gender/age/ethnicity/nationality/photo are never read.
# Display labels (`*_label`, see data/SCHEMA.md) win over raw values.
_ALIASES = {
    "row_id": ("row_id", "id"),
    "slug": ("id", "slug"),
    "name": ("name",),
    "one_liner": ("one_liner", "description", "idea", "bio", "summary"),
    "sector": ("sector_label", "sector", "business", "industry"),
    "stage": ("stage_label", "stage", "funding_stage", "last_round"),
    "country": ("country_label", "country", "geo"),
    "city": ("city",),
    "founded": ("founded", "founded_year", "year_founded"),
    "website": ("domain", "website", "url"),
    "funding_usd": ("funding_amount_usd", "total_funding_usd", "funding_usd"),
}
_UPPER = {"ai", "uk", "us", "usa", "uae", "eu", "b2b", "b2c", "saas", "cee", "dach", "sea",
          "latam", "iot", "hr", "vr", "ar", "ml", "d2c"}
_PRETTY = {"saas": "SaaS", "latam": "LatAm", "healthcare": "Health", "usa": "US"}


def _pretty(value: str) -> str:
    words = value.strip().split()
    out = []
    for w in words:
        lw = w.lower()
        out.append(_PRETTY.get(lw) or (lw.upper() if lw in _UPPER else lw.capitalize()))
    return " ".join(out)


def _label(value: str) -> str:
    """Keep ready-made labels ("B2B SaaS", "Southeast Asia"); prettify raw lowercase values."""
    return value.strip() if value != value.lower() else _pretty(value)


def _domain(website: str | None) -> Optional[str]:
    if not website:
        return None
    u = website if "://" in website else "https://" + website
    host = (urlparse(u).hostname or "").lower()
    return host[4:] if host.startswith("www.") else (host or None)


def _int(value: str | None) -> Optional[int]:
    try:
        return int(float(value)) if value not in (None, "") else None
    except ValueError:
        return None


def _float(value: str | None) -> Optional[float]:
    try:
        f = float(value) if value else None
    except ValueError:
        return None
    return f if f and f > 0 else None


@lru_cache(maxsize=1)
def _universe_options() -> UniverseOptions:
    rows = _csv_rows()
    return UniverseOptions(
        sector=sorted({r["sector"] for r in rows if r["sector"]}),
        country=sorted({r["country"] for r in rows if r["country"]}),
        stage=sorted({r["stage"] for r in rows if r["stage"]}),
        founded=sorted({r["founded"] for r in rows if r["founded"]}, reverse=True),
    )


def _row(r: dict, fit: Optional[int]) -> UniverseRow:
    company = Company(**{k: v for k, v in r.items() if not k.startswith("_")})
    return UniverseRow(company=company, fit=fit, funding_usd=r.get("_funding"))


@lru_cache(maxsize=1)
def _csv_rows() -> tuple[dict, ...]:
    """Lightweight dicts (Company fields only) for every CSV row. Loaded once."""
    path = config.companies_csv()
    rows: list[dict] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        cols = {c.lower().strip(): c for c in (reader.fieldnames or [])}
        pick = {k: next((cols[a] for a in aliases if a in cols), None) for k, aliases in _ALIASES.items()}
        for i, rec in enumerate(reader, start=1):
            get = lambda k: (rec.get(pick[k]) or "").strip() if pick[k] else ""  # noqa: E731
            name = get("name")
            if not name:
                continue
            row_id = _int(get("row_id")) or i
            given = get("slug")
            slug = given if given and not given.isdigit() else (slugify(name) or f"company-{row_id}")
            if slug in seen:
                slug = f"{slug}-{row_id}"
            seen.add(slug)
            domain = _domain(get("website"))
            one_liner = get("one_liner")
            rows.append({
                "id": slug,
                "row_id": row_id,
                "name": name,
                "one_liner": one_liner[:200],
                "sector": _label(get("sector")) or "Other",
                "stage": _label(get("stage")) or "Unknown",
                "country": _label(get("country")) or None,
                "city": get("city") or None,
                "founded": _int(get("founded")),
                "website": domain,
                "logo": f"https://www.google.com/s2/favicons?domain={domain}&sz=128" if domain else None,
                "_funding": _float(get("funding_usd")),
            })
    return tuple(rows)


def csv_available() -> bool:
    return config.companies_csv().exists()


def universe(fund_id: str, q: str | None = None, page: int = 1, page_size: int = 50,
             sector: str | None = None, country: str | None = None, stage: str | None = None,
             founded: int | None = None, ranked_ids: list[str] | None = None,
             sort: str | None = None) -> UniverseResponse:
    """`ranked_ids`: company ids ordered by meaning for `q` (Modal similar_companies). When given, the
    search shows name matches first, then the model's matches, then other word matches."""
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    filtered = any(v not in (None, "") for v in (q, sector, country, stage, founded))

    if csv_available():
        rows = _csv_rows()
        scores = store.get_memory(fund_id, "scores", {}) or {}
        dataset_size = len(rows)
        n_sectors = len({r["sector"] for r in rows})
        n_countries = len({r["country"] for r in rows if r["country"]})
        candidates: list[UniverseRow] = []
        rank = {cid: i for i, cid in enumerate(ranked_ids or [])}
        for r in rows:
            in_rank = r["id"] in rank
            if not _matches(r, q, sector, country, stage, founded):
                if not (in_rank and _matches(r, None, sector, country, stage, founded)):
                    continue
            candidates.append(_row(r, scores.get(str(r["row_id"]))))
        if rank and q:
            needle = q.lower()
            far = len(rank) + 1
            candidates.sort(key=lambda u: (0 if needle in u.company.name.lower() else 1,
                                           rank.get(u.company.id, far)))
        elif sort == "name":
            candidates.sort(key=lambda u: u.company.name.lower())
        elif sort == "founded":  # newest first, unknown last
            candidates.sort(key=lambda u: -(u.company.founded or 0))
        elif sort == "funding":  # most raised first, unknown last
            candidates.sort(key=lambda u: -(u.funding_usd or 0))
        elif scores and sort in (None, "", "fit"):
            candidates.sort(key=lambda u: -(u.fit if u.fit is not None else -1))
        total = len(candidates)
        start = (page - 1) * page_size
        return UniverseResponse(total=total, dataset_size=dataset_size, sectors=n_sectors,
                                countries=n_countries, page=page, page_size=page_size,
                                items=candidates[start:start + page_size],
                                options=_universe_options())

    base = _copy(mock("universe"))
    items = [u for u in base.items
             if _matches(u.company.model_dump(), q, sector, country, stage, founded)]
    start = (page - 1) * page_size
    return UniverseResponse(
        total=len(items) if filtered else base.total,
        dataset_size=base.dataset_size, sectors=base.sectors, countries=base.countries,
        page=page, page_size=page_size, items=items[start:start + page_size],
    )


def _matches(r: dict, q, sector, country, stage, founded) -> bool:
    if q:
        needle = q.lower()
        if needle not in r["name"].lower() and needle not in (r["one_liner"] or "").lower():
            return False
    if sector and (r["sector"] or "").lower() != sector.lower():
        return False
    if country and (r["country"] or "").lower() != country.lower():
        return False
    if stage and (r["stage"] or "").lower() != stage.lower():
        return False
    if founded and r["founded"] != founded:
        return False
    return True


# ---------------------------------------------------------------------------
# Companies (any page, then the CSV)
# ---------------------------------------------------------------------------


def _known_companies(fund_id: str) -> dict[str, Company]:
    found: dict[str, Company] = {}

    def add(c: Company) -> None:
        found.setdefault(c.id, c)

    for name in ("deals", "portfolio", "map"):
        try:
            page = (portfolio(fund_id) if name == "portfolio"
                    else _page(fund_id, name, _MOCK_MODELS[name]))  # type: ignore[arg-type]
        except NoData:
            continue
        if isinstance(page, DealsResponse):
            for i in page.items:
                add(i.company)
        elif isinstance(page, PortfolioResponse):
            for col in page.columns:
                for p in col.items + col.rest:
                    add(p.company)
        elif isinstance(page, MapResponse):
            for i in page.shortlist:
                add(i.company)
    for m in _all_memos(fund_id).values():
        add(m.company)
    if fund_id == demo_fund_id():
        for u in mock("universe").items:
            add(u.company)
    return found


def company(company_id: str, fund_id: str | None = None) -> Optional[Company]:
    fund_id = fund_id or config.default_fund_id()
    known = _known_companies(fund_id)
    if company_id in known:
        return apply_enrichment(known[company_id], enrichment(fund_id, company_id))
    if csv_available():
        row_id = _int(company_id.lstrip("#")) if company_id.lstrip("#").isdigit() else None
        for r in _csv_rows():
            if r["id"] == company_id or (row_id is not None and r["row_id"] == row_id):
                return Company(**r)
    return None


def deal_item(fund_id: str, company_id: str) -> Optional[DealFlowItem]:
    """The shortlist row for a company, from the deals page or the map's shortlist."""
    try:
        for item in _page(fund_id, "deals", DealsResponse).items:
            if item.company.id == company_id:
                return item
    except NoData:
        pass
    try:
        for item in _page(fund_id, "map", MapResponse).shortlist:
            if item.company.id == company_id:
                return item
    except NoData:
        pass
    return None
