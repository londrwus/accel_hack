"""Client for the Bellwether model on Modal (ml/modal_app.py, app `bellwether`, Volume `bellwether-data`).

Every call goes:  Modal (with a timeout)  ->  last good result from data/cache/modal/*.json  ->  offline fallback
shaped like the contract  ->  None. Nothing here raises or hangs. A slow cold start, a missing token, an app
that is not deployed yet or a stub that raises all end in a fallback, and the reason is kept for /api/health.

    r = await similar_companies("AI triage for GP practices", k=10)
    r.value        # the result dict (same shape whether it came from Modal, the cache or the fallback)
    r.source       # "modal" | "cache" | "fallback" | "none"
    r.reason       # plain English when it did not come from Modal, else None

Functions the ML track must deploy (signatures and return shapes are listed in the module-level docs of
each wrapper below and in FUNCTIONS):
    embed_all(batch_size: int = 256) -> dict
    similar_companies(query: str, k: int = 10, exclude_ids: list[str] | None = None) -> dict
    score_fit(fund_dna: dict, portfolio: list, k: int = 50, fund_id: str | None = None) -> dict
    backtest(fund: str) -> dict   (a `Backtest` from app/models.py, as a dict)

Settings (process env, then repo-root .env): MODAL_TOKEN_ID / MODAL_TOKEN_SECRET (or ~/.modal.toml),
MODAL_APP (default bellwether), MODAL_TIMEOUT_S (default 20), MODAL_SEARCH_TIMEOUT_S (default 5),
MODAL_DISABLED=1 forces the fallback (tests, or a stage with bad wifi).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import config

log = logging.getLogger("bellwether.modal")

FUNCTIONS = ("embed_all", "similar_companies", "score_fit", "backtest")

PROBE_TTL_S = 60.0  # how long a deployed/not-deployed answer is trusted
BREAKER_S = 30.0  # after a failure, skip Modal for this function for a while (keeps search snappy)
MIN_DATED_DEALS = 25  # a backtest holds out up to 20 deals and needs a few more to learn from
MIN_HELD_OUT = 10  # fewer held-out deals than this is "not enough history"

FEATURE_LABELS = ["Like the portfolio", "Right sector", "Right stage", "Right location", "Founded recently"]  # fit_parts
# feature_weights labels, same words as the Modal model (ml/fitcore.py WEIGHT_LABEL) and the design's backtest card
WEIGHT_LABELS = ["Similar to companies they own", "Right sector", "Right stage", "Right location", "Founded recently"]
FEATURE_COLORS = ["#5C7A63", "#8FAE96", "#B9CDBC", "#D3AD5E", "#E6D3A8"]  # from backtest.json (design)


# ---------------------------------------------------------------------------
# Windows: Modal's client prints rich text and emoji. Keep a cp1252 console from crashing on it.
# (The modal CLI itself should be run with PYTHONUTF8=1, see ml/modal_app.py.)
# ---------------------------------------------------------------------------


def _utf8_console() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")  # inherited by any subprocess (e.g. a `modal` CLI call)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        enc = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if enc and enc != "utf8" and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # pytest capture, closed streams...
                pass


_utf8_console()


# ---------------------------------------------------------------------------
# Result type and status bookkeeping
# ---------------------------------------------------------------------------


@dataclass
class ModalResult:
    value: Any
    source: str  # "modal" | "cache" | "fallback" | "none"
    reason: Optional[str] = None
    seconds: float = 0.0

    @property
    def used_fallback(self) -> bool:
        return self.source != "modal"

    @property
    def real(self) -> bool:
        """True when the value was computed by the model (now, or earlier and cached)."""
        return self.source in ("modal", "cache")


_fn_status: dict[str, dict] = {}  # fn -> {"ok", "reason", "at", "retry_at", "seconds"}
_probe: dict[str, Any] = {"deployed": None, "reason": "Not checked yet.", "at": 0.0}
_pending_backtests: dict[str, Any] = {}  # fund -> modal.FunctionCall (backtests run longer than a request)


def disabled() -> bool:
    return (config.setting("MODAL_DISABLED", "") or "").strip().lower() in ("1", "true", "yes")


def configured() -> bool:
    """A Modal token is available (env/.env, or the profile `modal token new` writes)."""
    if disabled():
        return False
    if config.setting("MODAL_TOKEN_ID") and config.setting("MODAL_TOKEN_SECRET"):
        return True
    return (Path.home() / ".modal.toml").exists()


def app_name() -> str:
    return config.modal_app_name()


def call_timeout() -> float:
    return config.modal_timeout_s()


def search_timeout() -> float:
    try:
        return float(config.setting("MODAL_SEARCH_TIMEOUT_S", "5") or "5")
    except ValueError:
        return 5.0


def _plain_reason(exc: BaseException) -> str:
    name = type(exc).__name__
    text = str(exc)
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "The model took too long to answer (it may be starting up)."
    if name == "NotFoundError" or "not found" in text.lower():
        return "The model isn't deployed on Modal yet."
    if name in ("AuthError", "PermissionError") or "token" in text.lower():
        return "Modal didn't accept our token."
    if name == "NotImplementedError" or "not built yet" in text:
        return "This part of the model isn't built yet."
    if name in ("ConnectionError", "OSError", "ClientClosed") or "connect" in text.lower():
        return "We couldn't reach Modal."
    return "The model ran into a problem."


def _record(fn: str, ok: bool, reason: Optional[str], seconds: float, app_missing: bool = False) -> None:
    now = time.monotonic()
    _fn_status[fn] = {"ok": ok, "reason": reason, "at": now, "seconds": round(seconds, 2),
                      "retry_at": 0.0 if ok else now + BREAKER_S}
    if ok:
        _probe.update(deployed=True, reason=None, at=now)
    elif app_missing:
        _probe.update(deployed=False, reason=reason, at=now)


def _skip_reason(fn: str) -> Optional[str]:
    """Why we shouldn't even try Modal right now (None = go ahead)."""
    if not configured():
        return "Modal is switched off." if disabled() else "No Modal token yet."
    now = time.monotonic()
    if _probe["deployed"] is False and now - _probe["at"] < PROBE_TTL_S:
        return _probe["reason"]
    st = _fn_status.get(fn)
    if st and not st["ok"] and now < st["retry_at"]:
        return st["reason"]
    return None


def reset_status() -> None:
    """Forget what we learned about Modal (tests; or after a fresh deploy)."""
    _fn_status.clear()
    _pending_backtests.clear()
    _probe.update(deployed=None, reason="Not checked yet.", at=0.0)


# ---------------------------------------------------------------------------
# The raw Modal call (patched in tests)
# ---------------------------------------------------------------------------


def _function(fn_name: str):
    import modal  # lazy: keeps startup light

    return modal.Function.from_name(app_name(), fn_name)


async def _remote(fn_name: str, *args: Any, **kwargs: Any) -> Any:
    return await _function(fn_name).remote.aio(*args, **kwargs)


# ---------------------------------------------------------------------------
# Disk cache: data/cache/modal/<fn>__<hint>__<hash>.json
# ---------------------------------------------------------------------------


def _cache_key(fn: str, args: tuple, kwargs: dict) -> str:
    blob = json.dumps([args, kwargs], sort_keys=True, default=str, ensure_ascii=False)
    digest = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]
    hint = ""
    if args and isinstance(args[0], str):
        hint = re.sub(r"[^a-z0-9]+", "-", args[0].lower()).strip("-")[:40]
    return f"{fn}__{hint}__{digest}" if hint else f"{fn}__{digest}"


def modal_cache_dir() -> Path:
    return config.CACHE_DIR / "modal"


def _cache_path(key: str) -> Path:
    return modal_cache_dir() / f"{key}.json"


def cache_read(key: str) -> Optional[dict]:
    path = _cache_path(key)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cache_write(key: str, fn: str, value: Any) -> None:
    path = _cache_path(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        payload = {"fn": fn, "saved_at": _now_iso(), "result": value}
        tmp.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError) as exc:
        log.warning("could not cache modal %s: %s", fn, type(exc).__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Generic call
# ---------------------------------------------------------------------------


async def call(fn: str, *args: Any, timeout: Optional[float] = None,
               fallback: Optional[Callable[[], Any]] = None, use_cache: bool = True,
               **kwargs: Any) -> ModalResult:
    """Modal -> cache -> fallback() -> None. Never raises.

    `fallback` is a zero-argument function so offline data is only built when it's needed.
    """
    key = _cache_key(fn, args, kwargs)
    reason = _skip_reason(fn)
    started = time.monotonic()
    if reason is None:
        try:
            value = await asyncio.wait_for(_remote(fn, *args, **kwargs),
                                           timeout=timeout if timeout is not None else call_timeout())
            seconds = time.monotonic() - started
            _record(fn, True, None, seconds)
            if use_cache:
                cache_write(key, fn, value)
            return ModalResult(value, "modal", None, seconds)
        except Exception as exc:  # TimeoutError, modal NotFoundError, remote exceptions...
            reason = _plain_reason(exc)
            app_missing = type(exc).__name__ == "NotFoundError"
            _record(fn, False, reason, time.monotonic() - started, app_missing=app_missing)
            log.warning("modal %s fell back: %s (%s)", fn, type(exc).__name__, reason)

    if use_cache:
        cached = cache_read(key)
        if cached is not None and "result" in cached:
            return ModalResult(cached["result"], "cache", reason, time.monotonic() - started)
    if fallback is not None:
        try:
            value = fallback()
            if value is not None:
                return ModalResult(value, "fallback", reason, time.monotonic() - started)
        except Exception:
            log.exception("modal %s offline fallback failed", fn)
    return ModalResult(None, "none", reason, time.monotonic() - started)


# ---------------------------------------------------------------------------
# similar_companies
# ---------------------------------------------------------------------------


async def similar_companies(query: str, k: int = 10, exclude_ids: Optional[list[str]] = None,
                            timeout: Optional[float] = None) -> ModalResult:
    """Companies most like `query` (free text, a company id, an exact name, or "#0193").

    Modal returns (and the fallback copies):
      {"query": str,
       "query_company": CompanyDict | None,          # set when the query named a company in the dataset
       "model": str,                                  # embedding model name
       "results": [CompanyDict + {"score": float}]}  # best first, len <= k, never the query company itself
    CompanyDict = {"id", "company_id", "row_id", "name", "one_liner", "sector", "stage", "country",
                   "founded", "website", "domain"}   # `id` == companies.csv `id` (slug)
    """
    k = max(1, min(int(k), 200))
    kwargs: dict[str, Any] = {"exclude_ids": list(exclude_ids)} if exclude_ids else {}
    return await call("similar_companies", query, k, timeout=timeout,
                      fallback=lambda: _similar_offline(query, k, exclude_ids or []), **kwargs)


async def search_ids(query: str, k: int = 100) -> Optional[list[str]]:
    """Company ids ranked by meaning, for the Startup Universe search. None unless the model answered
    (now or earlier, from the cache): the keyword search is used then."""
    if not query or not query.strip():
        return None
    r = await similar_companies(query.strip(), k=k, timeout=search_timeout())
    if not r.real or not isinstance(r.value, dict):
        return None
    ids = [str(x.get("id") or x.get("company_id")) for x in r.value.get("results", []) if isinstance(x, dict)]
    return [i for i in ids if i and i != "None"]


_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"a", "an", "and", "the", "for", "of", "to", "in", "on", "with", "that", "by", "at", "is", "are",
         "app", "platform", "company", "companies", "startup", "startups", "like", "help", "helps"}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 1}


def _company_rows() -> list[dict]:
    from . import data  # local import: data does not import this module, but keep import order simple

    if data.csv_available():
        try:
            return list(data._csv_rows())
        except Exception:
            log.exception("could not read companies.csv")
    rows = [u.company.model_dump() for u in data.mock("universe").items]
    return rows


def _company_dict(r: dict) -> dict:
    return {"id": r["id"], "company_id": r["id"], "row_id": r.get("row_id"), "name": r["name"],
            "one_liner": r.get("one_liner") or "", "sector": r.get("sector") or "",
            "stage": r.get("stage") or "", "country": r.get("country"), "founded": r.get("founded"),
            "website": r.get("website"), "domain": r.get("website")}


def _similar_offline(query: str, k: int, exclude: list[str]) -> dict:
    """Word overlap instead of embeddings. Same shape as Modal's answer."""
    rows = _company_rows()
    q = query.strip()
    qlow = q.lower().lstrip("#")
    query_row = next((r for r in rows if r["id"] == q or r["name"].lower() == q.lower()
                      or (qlow.isdigit() and r.get("row_id") == int(qlow))), None)
    text = f'{query_row["name"]} {query_row["one_liner"]} {query_row["sector"]}' if query_row else q
    want = _tokens(text)
    skip = set(exclude) | ({query_row["id"]} if query_row else set())
    scored = []
    if want:
        for r in rows:
            if r["id"] in skip:
                continue
            have = _tokens(f'{r["name"]} {r.get("one_liner") or ""} {r.get("sector") or ""}')
            hit = len(want & have)
            if hit:
                scored.append((hit / len(want), r))
    scored.sort(key=lambda t: (-t[0], t[1].get("row_id") or 0))
    results = [{**_company_dict(r), "score": round(s, 4)} for s, r in scored[:k]]
    return {"query": query, "query_company": _company_dict(query_row) if query_row else None,
            "model": "word match (offline fallback)", "results": results}


# ---------------------------------------------------------------------------
# score_fit
# ---------------------------------------------------------------------------


async def score_fit(fund_dna: dict, portfolio: list, k: int = 50, *, fund_id: Optional[str] = None,
                    timeout: Optional[float] = None) -> ModalResult:
    """Rank the dataset for one fund.

    Arguments sent to Modal:
      fund_dna:  FundDNA as a dict (app/models.py): {"summary", "stage", "geo", "cheque",
                 "sectors": [{"name", "count", "share", "color"}], "themes": [str], "sources": [...]}
      portfolio: list of portfolio companies. Each item is either a dataset company id (str) or a dict
                 {"name": str, "one_liner": str, "sector"?: str, "stage"?: str, "country"?: str, "website"?: str}
      k:         how many to return (the Deal Finder asks for 50)

    Modal returns (and the fallback copies):
      {"model": str,
       "n_scored": int,                                 # rows scored (≈10k)
       "score_seconds": float,                          # time to score the whole dataset
       "feature_weights": [{"label": str, "share": float}],   # shares sum to 1 (Backtest.feature_weights)
       "results": [CompanyDict + {"fit": int 0..100, "score": float 0..1,
                                  "fit_parts": [{"label": str, "value": float 0..1}]}]}   # best first
    fit_parts labels: "Like the portfolio", "Right stage", "Right location", "Right sector", "Fits the thesis",
    "Founded recently". feature_weights labels: "Similar to companies they own", "Matches the written thesis",
    "Right sector", "Right stage", "Right location", "Founded recently" (the model's always carry a `color` too).
    The Modal model (ml/fitcore.py run_score_fit) also returns, per result: "rank", "logit", "parts"
    ({label: 0..1}, same as fit_parts), "like" (closest portfolio company id or None), "contributions"
    ([{feature, part, label, value, raw, impact}], plain-English reasons, best first) and "nearest_portfolio"
    ([{company_id, name, score}]); and at the top: "fund_id", "k", "dataset_size", "portfolio"
    ({matched, external, unmatched}), "thesis_text", "model_info", "total_seconds". The offline fallback has
    none of these extras, so read them with .get().
    Never used as features: founder gender/age/ethnicity/nationality, investors, discovery_source.
    """
    fund_dna = fund_dna or {}
    k = max(1, min(int(k), 500))
    args: tuple = (fund_dna, list(portfolio or []), k) + ((fund_id,) if fund_id else ())  # by position
    r = await call("score_fit", *args, timeout=timeout,
                   fallback=lambda: _score_offline(fund_dna, portfolio or [], k, fund_id))
    if r.real and isinstance(r.value, dict):  # cache rows -> Startup Universe fit column
        _maybe_save_scores(fund_id, r.value)
    return r


def _maybe_save_scores(fund_id: Optional[str], value: dict) -> None:
    if not fund_id:
        return
    from . import data

    scores = {int(x["row_id"]): int(x["fit"]) for x in value.get("results", [])
              if isinstance(x, dict) and x.get("row_id") is not None and x.get("fit") is not None}
    if scores:
        try:
            data.save_scores(fund_id, scores)
        except Exception:
            log.exception("could not save scores")


def _score_offline(fund_dna: dict, portfolio: list, k: int, fund_id: Optional[str]) -> dict:
    """Plain rules instead of the trained model, so a run without Modal still gets a ranked list."""
    from . import data

    started = time.monotonic()
    if fund_id and fund_id == data.demo_fund_id() and not data.csv_available():
        results = [{**_company_dict(i.company.model_dump()), "fit": i.fit, "score": i.fit / 100,
                    "fit_parts": [p.model_dump() for p in i.fit_parts]}
                   for i in data.mock("deals").items]
        results.sort(key=lambda x: -x["fit"])
        return {"model": "design examples (offline fallback)", "n_scored": len(results),
                "score_seconds": 0.0, "feature_weights": _even_weights(), "results": results[:k]}

    rows = _company_rows()
    sectors = {str(s.get("name", "")).lower() for s in fund_dna.get("sectors") or [] if isinstance(s, dict)}
    stage_text = str(fund_dna.get("stage") or "").lower()
    geo_text = str(fund_dna.get("geo") or "").lower()
    theme_words = _tokens(" ".join(str(t) for t in fund_dna.get("themes") or []))
    for p in portfolio:
        if isinstance(p, dict):
            theme_words |= _tokens(f'{p.get("one_liner", "")} {p.get("sector", "")}')
    portfolio_ids = {p for p in portfolio if isinstance(p, str)}
    this_year = datetime.now(timezone.utc).year
    weights = [0.41, 0.24, 0.18, 0.11, 0.06]  # same order as FEATURE_LABELS
    results = []
    for r in rows:
        if r["id"] in portfolio_ids:
            continue
        words = _tokens(f'{r["name"]} {r.get("one_liner") or ""}')
        like = min(1.0, len(words & theme_words) / 3) if theme_words else 0.0
        sector = 1.0 if (r.get("sector") or "").lower() in sectors else 0.0
        stage = 1.0 if r.get("stage") and r["stage"].lower() in stage_text else 0.0
        geo = 1.0 if r.get("country") and r["country"].lower() in geo_text else 0.0
        founded = r.get("founded")
        recent = max(0.0, 1 - (this_year - founded) / 10) if founded else 0.0
        parts = [like, sector, stage, geo, recent]
        score = sum(w * v for w, v in zip(weights, parts))
        if score <= 0:
            continue
        results.append({**_company_dict(r), "fit": int(round(score * 100)), "score": round(score, 4),
                        "fit_parts": [{"label": FEATURE_LABELS[i], "value": round(parts[i], 2)}
                                      for i in (0, 2, 3)]})
    results.sort(key=lambda x: (-x["score"], x.get("row_id") or 0))
    return {"model": "simple rules (offline fallback)", "n_scored": len(rows),
            "score_seconds": round(time.monotonic() - started, 2),
            "feature_weights": [{"label": l, "share": w} for l, w in zip(WEIGHT_LABELS, weights)],
            "results": results[:k]}


def _even_weights() -> list[dict]:
    return [{"label": l, "share": round(1 / len(WEIGHT_LABELS), 2)} for l in WEIGHT_LABELS]


# ---------------------------------------------------------------------------
# backtest
# ---------------------------------------------------------------------------


def _investor_paths() -> tuple[Path, Path]:
    index = Path(config.setting("INVESTOR_INDEX_JSON", str(config.DATA_DIR / "investor_index.json")) or "")
    inv = Path(config.setting("INVESTORS_JSON", str(config.DATA_DIR / "investors.json")) or "")
    return index, inv


def dated_deals(fund: str) -> Optional[int]:
    """How many of the fund's portfolio companies in the dataset have a date. None = we can't tell locally."""
    index_path, investors_path = _investor_paths()
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    family = (index.get("fund_families") or {}).get(fund)
    if family and "dated_any" in family:
        return int(family["dated_any"])
    info = (index.get("investors") or {}).get(fund)
    if info and "dated_any" in info:
        return int(info["dated_any"])
    try:  # not in the index: count in investors.json
        investors = json.loads(investors_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return sum(1 for d in investors.get(fund, []) if d.get("date"))


def not_enough_history(fund: str, held_out: int = 0) -> dict:
    """A Backtest with no numbers: the UI shows "Not enough history for this fund"."""
    from . import data

    rows = len(_company_rows()) if data.csv_available() else data.mock("universe").dataset_size
    return {
        "fund_id": fund, "enough_history": False, "held_out": int(held_out), "top_percent": 5,
        "methods": [], "feature_weights": [],
        "model_card": {"trained_on": "Modal", "data": f"{rows:,} startups",
                       "method": "Text match + scoring model", "retrains": "Every night",
                       "never_used": ["Gender", "Age", "Ethnicity"]},
        "score_seconds": 0.0, "trained_at": _now_iso(), "trained_label": "Not enough history",
    }


def _normalise_backtest(fund: str, value: Any) -> Optional[dict]:
    """Validate a Modal answer against the contract. Too few held-out deals -> no numbers."""
    from .models import Backtest

    if not isinstance(value, dict):
        return None
    value = {**value, "fund_id": value.get("fund_id") or fund}
    for i, fw in enumerate(value.get("feature_weights") or []):
        if isinstance(fw, dict) and not fw.get("color"):
            fw["color"] = FEATURE_COLORS[i % len(FEATURE_COLORS)]
    if not value.get("trained_label"):
        value["trained_label"] = "Just now"
    if not value.get("trained_at"):
        value["trained_at"] = _now_iso()
    try:
        bt = Backtest.model_validate(value).model_dump(mode="json")
    except Exception:
        log.warning("modal backtest for %s did not match the contract", fund)
        return None
    if not bt["enough_history"] or bt["held_out"] < MIN_HELD_OUT:
        return not_enough_history(fund, bt["held_out"])
    return bt


def backtest_file(fund: str) -> Path:
    return config.CACHE_DIR / f"backtest_{fund}.json"


def _save_backtest(fund: str, bt: dict) -> None:
    path = backtest_file(fund)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(bt, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("could not save backtest for %s: %s", fund, type(exc).__name__)


async def _spawn_backtest(fund: str):
    return await _function("backtest").spawn.aio(fund)


async def _poll_call(fc, wait_s: float) -> Any:
    return await fc.get.aio(timeout=wait_s)


async def backtest(fund: str, timeout: Optional[float] = None) -> ModalResult:
    """The backtest for the Startup Universe page. Value: a `Backtest` dict, or None (-> 404).

    1. data/cache/backtest_{fund}.json (written here, or by the Modal job)    source "cache"
    2. not enough dated deals in the dataset -> enough_history false, no numbers   source "fallback"
    3. Modal backtest(fund): spawned once, then polled; a request waits at most `timeout`   source "modal"
       (a backtest can run longer than a request; the next request picks the result up)
    Never the placeholder numbers from frontend/src/mocks/backtest.json.
    """
    from . import data

    started = time.monotonic()
    try:
        saved = data.backtest(fund)
    except Exception:
        saved = None
        log.warning("backtest file for %s is not valid; ignoring it", fund)
    if saved is not None:
        return ModalResult(saved.model_dump(mode="json"), "cache", None, 0.0)

    dated = dated_deals(fund)
    if dated is not None and dated < MIN_DATED_DEALS:
        return ModalResult(not_enough_history(fund), "fallback",
                           f"Only {dated} of this fund's deals are in the dataset with a date.", 0.0)

    reason = _skip_reason("backtest")
    if reason is not None:
        return ModalResult(None, "none", reason, 0.0)

    wait = timeout if timeout is not None else call_timeout()
    try:
        fc = _pending_backtests.get(fund)
        if fc is None:
            fc = await asyncio.wait_for(_spawn_backtest(fund), timeout=wait)
            _pending_backtests[fund] = fc
        remaining = max(0.1, wait - (time.monotonic() - started))
        value = await asyncio.wait_for(_poll_call(fc, remaining), timeout=remaining + 2)
    except Exception as exc:
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) and fund in _pending_backtests:
            return ModalResult(None, "none", "The backtest is still running on Modal. Check back in a minute.",
                               time.monotonic() - started)
        _pending_backtests.pop(fund, None)
        reason = _plain_reason(exc)
        _record("backtest", False, reason, time.monotonic() - started,
                app_missing=type(exc).__name__ == "NotFoundError")
        return ModalResult(None, "none", reason, time.monotonic() - started)

    _pending_backtests.pop(fund, None)
    _record("backtest", True, None, time.monotonic() - started)
    bt = _normalise_backtest(fund, value)
    if bt is None:
        return ModalResult(None, "none", "The model's backtest didn't match what the page expects.",
                           time.monotonic() - started)
    _save_backtest(fund, bt)
    return ModalResult(bt, "modal", None, time.monotonic() - started)


# ---------------------------------------------------------------------------
# embed_all (a one-off job: start it, don't wait for it)
# ---------------------------------------------------------------------------


async def start_embed_all(batch_size: int = 256) -> ModalResult:
    """Starts embed_all on Modal and returns {"call_id": str} at once. Usually run from the CLI instead:
    `PYTHONUTF8=1 modal run modal_app.py::embed_all` (from ml/).

    embed_all(batch_size) returns {"model", "dim", "count", "load_seconds", "encode_seconds",
    "total_seconds", "created_at"} and writes embeddings.npy / embedding_ids.json to the Volume.
    """
    reason = _skip_reason("embed_all")
    if reason is not None:
        return ModalResult(None, "none", reason)
    try:
        fc = await asyncio.wait_for(_function("embed_all").spawn.aio(batch_size), timeout=call_timeout())
        return ModalResult({"call_id": fc.object_id}, "modal")
    except Exception as exc:
        return ModalResult(None, "none", _plain_reason(exc))


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


async def _hydrate(fn: str) -> None:
    await _function(fn).hydrate.aio()


async def probe(force: bool = False, timeout: float = 5.0) -> dict:
    """Is the app deployed? A name lookup only (no container starts). Cached for PROBE_TTL_S."""
    if not configured():
        _probe.update(deployed=False, reason="Modal is switched off." if disabled() else "No Modal token yet.",
                      at=time.monotonic())
        return dict(_probe)
    if not force and _probe["deployed"] is not None and time.monotonic() - _probe["at"] < PROBE_TTL_S:
        return dict(_probe)
    try:
        await asyncio.wait_for(_hydrate("similar_companies"), timeout=timeout)
        _probe.update(deployed=True, reason=None, at=time.monotonic())
    except Exception as exc:
        _probe.update(deployed=False, reason=_plain_reason(exc), at=time.monotonic())
    return dict(_probe)


async def health() -> dict:
    p = await probe()
    now = time.monotonic()
    functions = {}
    for fn in FUNCTIONS:
        st = _fn_status.get(fn)
        if st is None:
            functions[fn] = {"status": "untried", "reason": None, "seconds": None}
        else:
            functions[fn] = {"status": "ok" if st["ok"] else "fallback", "reason": st["reason"],
                             "seconds": st["seconds"], "checked_s_ago": round(now - st["at"], 1)}
    return {
        "modal": "deployed" if p["deployed"] else "fallback",
        "modal_reason": p["reason"],
        "modal_app": app_name(),
        "modal_configured": configured(),
        "modal_functions": functions,
        "modal_timeout_s": call_timeout(),
        "modal_cache_files": len(list(modal_cache_dir().glob("*.json"))) if modal_cache_dir().exists() else 0,
    }


# Backwards compatible with app/tools/modal_client.call (returns (value, used_fallback)).
async def call_pair(fn: str, *args: Any, fallback: Any = None, timeout: Optional[float] = None,
                    **kwargs: Any) -> tuple[Any, bool]:
    r = await call(fn, *args, timeout=timeout, fallback=(lambda: fallback), **kwargs)
    if r.source == "none":
        return fallback, True
    return r.value, r.used_fallback


__all__ = ["ModalResult", "FUNCTIONS", "configured", "disabled", "call", "call_pair", "similar_companies",
           "search_ids", "score_fit", "backtest", "start_embed_all", "probe", "health", "reset_status",
           "not_enough_history", "dated_deals"]
