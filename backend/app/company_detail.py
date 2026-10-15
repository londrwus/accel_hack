"""GET /api/companies/{id}/detail: everything about one company and how it scored for the current fund.

Score, in order of preference:
  1. the fund's shortlist (deals page) + the latest run's score checkpoint (fit, parts, judge, closest company)
  2. the Modal model's cached answer for this fund (parts, plain-English reasons, nearest portfolio companies)
  3. the saved fit for every dataset row (Startup Universe column) + a quick local breakdown
  4. a quick local estimate from simple rules when the fund has a thesis
  5. "Not scored for this fund yet"
Funding and investors are shown for context only. They are never used for scoring.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import threading
from functools import lru_cache
from typing import Any, Optional

from . import config, data, modal_client, store
from .models import (
    SimilarResponse,
    Company,
    CompanyDetail,
    CompanyScore,
    FeatureWeight,
    FitPart,
    FundingInfo,
    MarketInfo,
    NearPortfolio,
    ScoreReason,
    Signal,
    SimilarCompany,
    Source,
)
from .tools import dataset

log = logging.getLogger("bellwether.detail")

JUDGE_PART = "Fits the thesis (judge)"
_CSV_COLS = ("row_id", "id", "name", "website", "domain", "summary", "problem", "business_model", "customers",
             "market", "stage_label", "stage_reported", "funding_amount", "funding_currency", "funding_amount_usd",
             "funding_date", "first_funding_date", "last_funding_date", "n_rounds", "site_status", "market_scope", "market_size",
             "market_cagr", "market_year", "market_source", "investors")


# ---------------------------------------------------------------------------
# Dataset row (full text columns, read on demand)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _csv_index() -> tuple[dict[str, dict], dict[int, dict]]:
    """Every CSV row (only the columns the page shows), indexed by id and row_id. Built once."""
    by_id: dict[str, dict] = {}
    by_row: dict[int, dict] = {}
    path = config.companies_csv()
    if not path.exists():
        return by_id, by_row
    with path.open(encoding="utf-8-sig", newline="") as f:
        for rec in csv.DictReader(f):
            r = {c: (rec.get(c) or "").strip() for c in _CSV_COLS}
            if r.get("id"):
                by_id.setdefault(r["id"], r)
            if r.get("row_id", "").isdigit():
                by_row.setdefault(int(r["row_id"]), r)
    return by_id, by_row


def csv_record(company_id: str, row_id: Optional[int]) -> Optional[dict]:
    by_id, by_row = _csv_index()
    rec = by_id.get(company_id) or (by_row.get(row_id) if row_id is not None else None)
    return dict(rec) if rec else None


def _int(v: Any) -> Optional[int]:
    try:
        return int(float(v)) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _money(amount: str, currency: str, usd: str) -> Optional[str]:
    value, cur = (_int(usd), "USD") if _int(usd) else (_int(amount), (currency or "USD").upper())
    if not value:
        return None
    sym = {"USD": "$", "GBP": "£", "EUR": "€"}.get(cur, cur + " ")
    if value >= 1_000_000_000:
        n = f"{value / 1e9:.1f}B"
    elif value >= 1_000_000:
        n = f"{value / 1e6:.1f}M"
    elif value >= 1_000:
        n = f"{value / 1e3:.0f}K"
    else:
        n = str(value)
    return sym + n.replace(".0", "")


# ---------------------------------------------------------------------------
# Stored score sources
# ---------------------------------------------------------------------------


def _ckpt_top(fund_id: str, company_id: str) -> tuple[Optional[dict], Optional[int]]:
    for run in store.list_runs(fund_id=fund_id, limit=10):
        ck = store.get_memory(fund_id, f"ckpt:{run['id']}:scores")
        if isinstance(ck, dict) and ck.get("top"):
            for i, t in enumerate(ck["top"], start=1):
                if t.get("company_id") == company_id:
                    return t, i
            return None, None
    return None, None


_modal_lock = threading.Lock()
_modal_cache: dict[str, Any] = {"sig": None, "files": []}


def _modal_files() -> list[dict]:
    """Cached Modal score_fit answers, newest first: [{saved_at, fund_id, weights, by_id}]."""
    d = modal_client.modal_cache_dir()
    paths = sorted(d.glob("score_fit__*.json")) if d.exists() else []
    sig = tuple((p.name, p.stat().st_mtime) for p in paths)
    with _modal_lock:
        if _modal_cache["sig"] == sig:
            return _modal_cache["files"]
        files = []
        for p in paths:
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            res = raw.get("result") or raw.get("value") or {}
            if not isinstance(res, dict) or not res.get("results"):
                continue
            files.append({"saved_at": raw.get("saved_at") or "", "fund_id": res.get("fund_id"),
                          "weights": res.get("feature_weights") or [],
                          "by_id": {str(x.get("id") or x.get("company_id")): x for x in res["results"]
                                    if isinstance(x, dict)}})
        files.sort(key=lambda f: f["saved_at"], reverse=True)
        _modal_cache.update(sig=sig, files=files)
        return files


def _fund_files(fund_id: str) -> list[dict]:
    """Model answers that belong to this fund: tagged with it, or untagged and saved during one of its runs."""
    runs = store.list_runs(fund_id=fund_id, limit=20)
    windows = [(r.get("started_at") or "", r.get("finished_at") or "9999") for r in runs]
    out = []
    for f in _modal_files():
        if f["fund_id"] == fund_id:
            out.append(f)
        elif f["fund_id"] is None and any(a and a <= f["saved_at"] <= b for a, b in windows):
            out.append(f)
    return out


_local_lock = threading.Lock()
_local: dict[str, tuple[str, dict]] = {}  # fund -> (dna json, {company_id: candidate})


def _local_scores(fund_id: str, dna: dict) -> dict:
    key = json.dumps(dna, sort_keys=True, default=str)
    with _local_lock:
        hit = _local.get(fund_id)
        if hit and hit[0] == key:
            return hit[1]
    fund = data.get_fund(fund_id)
    port = dataset.fund_portfolio(fund_id, fund.name)
    weights = store.get_memory(fund_id, "thesis_weights", {}) or {}
    cands, _ = dataset.score(dna, port, k=100_000, sector_weights=weights)
    by_id = {c["row"]["id"]: c for c in cands}
    with _local_lock:
        _local[fund_id] = (key, by_id)
    return by_id


def _fund_dna(fund_id: str) -> Optional[dict]:
    dna = store.get_memory(fund_id, "fund_dna")
    if isinstance(dna, dict) and dna:
        return dna
    f = data.get_fund(fund_id)
    return f.dna.model_dump() if f.dna else None


def _name_of(company_id: Optional[str], fund_id: str) -> Optional[str]:
    if not company_id:
        return None
    c = data.company(company_id, fund_id)
    return c.name if c else company_id.replace("-", " ").title()


def build_score(fund_id: str, company: Company, deal) -> CompanyScore:
    cid = company.id
    top, top_rank = _ckpt_top(fund_id, cid)
    files = _fund_files(fund_id)
    modal_row = next((f["by_id"][cid] for f in files if cid in f["by_id"]), None)
    weights_raw = next((f["weights"] for f in files if f["weights"]), None)
    if not weights_raw:
        bt = data.backtest(fund_id)
        weights_raw = [w.model_dump() for w in bt.feature_weights] if bt else []
    palette = ["#5C7A63", "#8FAE96", "#B9CDBC", "#D3AD5E", "#E6D3A8", "#7FA3C0"]
    feature_weights = [FeatureWeight(label=w["label"], share=float(w.get("share") or 0),
                                     color=w.get("color") or palette[i % len(palette)])
                       for i, w in enumerate(weights_raw) if isinstance(w, dict) and w.get("label")]

    s = CompanyScore(scored=False, source_label="Not scored for this fund yet", feature_weights=feature_weights)

    # Parts: model's six parts when we have them, then whatever the shortlist / checkpoint add (the judge).
    parts: dict[str, float] = {}
    if modal_row:
        for p in modal_row.get("fit_parts") or []:
            parts[p["label"]] = float(p["value"])
        s.reasons = [ScoreReason(label=c.get("label") or c.get("part") or "", impact=round(float(c.get("impact") or 0), 3))
                     for c in modal_row.get("contributions") or [] if c.get("label")]
        s.nearest_portfolio = [NearPortfolio(company_id=n.get("company_id"), name=n.get("name") or
                                             _name_of(n.get("company_id"), fund_id) or "",
                                             score=n.get("score"))
                               for n in modal_row.get("nearest_portfolio") or []][:5]
        s.fit = _int(modal_row.get("fit"))
        s.model_fit = s.fit
        s.rank = _int(modal_row.get("rank"))
        s.scored = True
        s.source_label = "Scored by the Bellwether model"
    if top:
        for label, v in (top.get("parts") or {}).items():
            parts.setdefault(label, float(v))
        if top.get("judge") is not None:
            s.judge = float(top["judge"])
            parts[JUDGE_PART] = s.judge
        s.fit = _int(top.get("fit"))
        s.model_fit = _int(top.get("model_fit")) or s.model_fit
        s.rank = top_rank
        s.scored = True
        s.source_label = "From the latest run"
        if not s.nearest_portfolio and top.get("like") and top["like"] != "nothing":
            s.nearest_portfolio = [NearPortfolio(company_id=top["like"], name=_name_of(top["like"], fund_id) or "")]
    if deal is not None:
        for p in deal.fit_parts:
            parts.setdefault(p.label, p.value)
            if p.label == JUDGE_PART:
                s.judge = p.value
        s.fit = deal.fit
        s.rank = deal.rank
        s.why = list(deal.why)
        s.scored = True
        s.source_label = "On this fund's shortlist"

    if not s.scored and company.row_id is not None:
        saved = (store.get_memory(fund_id, "scores", {}) or {}).get(str(company.row_id))
        dna = _fund_dna(fund_id)
        local = None
        if dna:
            try:
                local = _local_scores(fund_id, dna).get(cid)
            except Exception:
                log.exception("local score failed")
        if saved is not None:
            s.fit, s.scored = int(saved), True
            s.source_label = "Scored by the latest run (breakdown is a quick estimate)"
        if local:
            parts.update(local["parts"])
            if s.fit is None:
                s.fit, s.scored = int(local["fit"]), True
                s.source_label = "Quick estimate from simple rules"
            if local.get("like"):
                s.nearest_portfolio = [NearPortfolio(company_id=local["like"]["id"], name=local["like"]["name"])]

    s.parts = [FitPart(label=k, value=round(max(0.0, min(1.0, v)), 2)) for k, v in parts.items()]
    if not s.reasons and s.nearest_portfolio and s.nearest_portfolio[0].name:
        s.reasons = [ScoreReason(label=f"Closest company in the portfolio: {s.nearest_portfolio[0].name}", impact=1.0)]
    return s


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def _portfolio_item(fund_id: str, company_id: str):
    try:
        for col in data.portfolio(fund_id).columns:
            for p in col.items:
                if p.company.id == company_id:
                    return p
    except data.NoData:
        pass
    return None


def _memo_id(fund_id: str, company_id: str) -> Optional[str]:
    try:
        for m in data.memos(fund_id).items:
            if m.company.id == company_id or m.id == company_id:
                return m.id
    except data.NoData:
        pass
    return None


async def _similar(company: Company, in_dataset: bool, fund_id: str) -> tuple[list[SimilarCompany], str]:
    query = company.id if in_dataset else f"{company.name}. {company.one_liner}".strip()
    try:
        r = await modal_client.similar_companies(query, k=7, exclude_ids=[company.id], timeout=3.0)
    except Exception:
        log.exception("similar companies failed")
        return [], ""
    if not isinstance(r.value, dict):
        return [], ""
    out: list[SimilarCompany] = []
    for x in r.value.get("results", []):
        xid = str(x.get("id") or x.get("company_id") or "")
        if not xid or xid == company.id:
            continue
        c = data.company(xid, fund_id)
        if c is None:
            continue
        out.append(SimilarCompany(company=c, score=round(float(x["score"]), 3) if x.get("score") is not None else None))
    return out[:6], ("Bellwether model" if r.real else "Word match (model offline)")


async def similar(company_id: str, fund_id: str) -> Optional[SimilarResponse]:
    company = await asyncio.to_thread(data.company, company_id, fund_id)
    if company is None:
        return None
    rec = await asyncio.to_thread(csv_record, company.id, company.row_id) if data.csv_available() else None
    items, source = await _similar(company, rec is not None, fund_id)
    return SimilarResponse(similar=items, similar_source=source)


async def detail(company_id: str, fund_id: str, with_similar: bool = True) -> Optional[CompanyDetail]:
    company = await asyncio.to_thread(data.company, company_id, fund_id)
    if company is None:
        return None
    rec = await asyncio.to_thread(csv_record, company.id, company.row_id) if data.csv_available() else None
    if rec and company.row_id is None and rec.get("row_id", "").isdigit():
        company.row_id = int(rec["row_id"])
    deal = data.deal_item(fund_id, company.id)
    port = _portfolio_item(fund_id, company.id)
    score_task = asyncio.to_thread(build_score, fund_id, company, deal)
    if with_similar:
        score, (similar, similar_source) = await asyncio.gather(score_task, _similar(company, rec is not None, fund_id))
    else:
        score, similar, similar_source = await score_task, [], ""

    fund = data.get_fund(fund_id)
    d = CompanyDetail(company=company, fund_id=fund_id, fund_name=fund.name, in_dataset=rec is not None,
                      score=score, stage_estimated="estimated" in (company.stage or "").lower(),
                      similar=similar, similar_source=similar_source)
    if rec:
        d.summary = rec["summary"] or None
        d.problem = rec["problem"] or None
        d.business_model = rec["business_model"] or None
        d.customers = rec["customers"] or None
        if any(rec[k] for k in ("market", "market_scope", "market_size", "market_cagr")):
            d.market = MarketInfo(description=rec["market"] or None, scope=rec["market_scope"] or None,
                                  size=rec["market_size"] or None, cagr=rec["market_cagr"] or None,
                                  year=_int(rec["market_year"]), source=rec["market_source"] or None)
        investors = [i.strip() for i in rec["investors"].split("|") if i.strip()]
        amount = _money(rec["funding_amount"], rec["funding_currency"], rec["funding_amount_usd"])
        if investors or amount or rec["last_funding_date"] or _int(rec["n_rounds"]):
            d.funding = FundingInfo(amount_label=amount,
                                    last_round_date=rec["last_funding_date"] or rec["funding_date"] or None,
                                    first_round_date=rec["first_funding_date"] or None,
                                    rounds=_int(rec["n_rounds"]), investors=investors[:30])

    enr = data.enrichment(fund_id, company.id) if not rec else None
    if enr:
        d.summary = enr.get("description") or enr.get("one_liner")
        d.business_model = enr.get("business_model")
        d.customers = enr.get("customers")

    signals: list[Signal] = []
    if deal is not None:
        signals += deal.signals
        d.deal_status = deal.status
        d.conflict_with = deal.conflict_with
    if port is not None:
        signals += port.signals
        d.health = port.health
    seen: set[str] = set()
    d.signals = [x for x in signals if not (x.label in seen or seen.add(x.label))]
    d.memo_id = (deal.memo_id if deal is not None and deal.memo_id else None) or _memo_id(fund_id, company.id)

    sources: list[Source] = []
    if company.row_id is not None and rec:
        sources.append(Source(label=f"dataset #{company.row_id:04d}", row_id=company.row_id))
    if company.website:
        url = company.website if "://" in company.website else f"https://{company.website}"
        sources.append(Source(label=company.website, url=url))
    for x in d.signals:
        if x.source_url and all(s.url != x.source_url for s in sources):
            sources.append(Source(label=x.source_url.split("//")[-1].split("/")[0], url=x.source_url))
    for s in (enr or {}).get("sources", []):
        if s.get("url") and all(x.url != s["url"] for x in sources):
            sources.append(Source(label=s.get("label") or s["url"], url=s["url"]))
    if d.market and d.market.source:
        sources.append(Source(label=f"Market size: {d.market.source}"))
    d.sources = sources
    return d
