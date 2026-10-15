"""Bellwether model on Modal: embeddings + similarity + fund-fit scoring + backtest.

App:    bellwether
Volume: bellwether-data, mounted at /data
    /data/companies.csv        cleaned dataset (uploaded by ml/upload.py)
    /data/investors.json       investor slug -> portfolio list (uploaded by ml/upload.py)
    /data/embeddings.npy       float32 [n, dim], L2-normalised, row i <-> embedding_ids.json[i]
    /data/embedding_ids.json   list of company ids (Company.id), same order as embeddings.npy
    /data/embed_meta.json      model name, dim, count, timings
    /data/cache/               backtest_{fund}.json etc. (written by backtest())

The backend calls these by name with modal.Function.from_name("bellwether", <name>):
    embed_all()                                   -> dict (meta)
    similar_companies(query, k=10, exclude_ids=None) -> {"query", "query_company", "model", "results": [Company + score]}
    score_fit(fund_dna, portfolio, k=50, fund_id=None) -> {"model": str, "n_scored", "feature_weights",
                                                     "results": [Company + fit, score, parts, fit_parts, like, ...], ...}
    backtest(fund: str)                           -> Backtest-shaped dict, also saved to /data/cache/backtest_{fund}.json
Check the deployed app exactly as the backend calls it:  python -I ml/check_deployed.py  (from the repo root)

Deploy (PowerShell or bash, from ml/):  PYTHONUTF8=1 modal deploy modal_app.py
Embed:                                  PYTHONUTF8=1 modal run modal_app.py::embed_all
Smoke test:                             PYTHONUTF8=1 modal run modal_app.py::smoke
Fit smoke test:                         PYTHONUTF8=1 modal run modal_app.py::smoke_fit
Backtests (+ save to ../data/cache):    PYTHONUTF8=1 modal run modal_app.py::run_backtests
The scoring logic lives in fitcore.py (pure numpy + scikit-learn), shipped into the image.

Never used as features anywhere in this file: discovery_source, investors, investor_ids (they leak the label).
"""

from __future__ import annotations

import time

import modal

APP_NAME = "bellwether"
VOLUME_NAME = "bellwether-data"
DATA_DIR = "/data"
MODEL_DIR = "/models"
EMBED_MODEL = "BAAI/bge-base-en-v1.5"  # 768-dim, 110M params, strong on short English text
# BGE's recommended prefix for short search queries against passages (not used for company-to-company lookups).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)


def _download_model() -> None:
    from sentence_transformers import SentenceTransformer

    SentenceTransformer(EMBED_MODEL, cache_folder=MODEL_DIR)


image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "torch==2.7.1",
        "sentence-transformers==4.1.0",
        "transformers>=4.41,<5",
        "numpy==2.2.6",
        "scikit-learn==1.6.1",
    )
    .env({"HF_HOME": MODEL_DIR, "TOKENIZERS_PARALLELISM": "false"})
    .run_function(_download_model)  # bake the weights into the image: no download at cold start
    .env({"HF_HUB_OFFLINE": "1"})
    .add_local_python_source("fitcore")  # ml/fitcore.py: the scoring + backtest logic (numpy + scikit-learn)
)


# ---------------------------------------------------------------------------
# Shared helpers (run inside Modal containers)
# ---------------------------------------------------------------------------

_STATE: dict = {}  # per-container cache: model, embeddings, companies


def _read_companies() -> list[dict]:
    import csv

    with open(f"{DATA_DIR}/companies.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _load_model(device: str | None = None):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBED_MODEL, cache_folder=MODEL_DIR, device=device)


def _state() -> dict:
    """Load model + embeddings + company rows once per container."""
    if _STATE:
        return _STATE
    import json
    import os

    import numpy as np

    t0 = time.time()
    volume.reload()
    if not os.path.exists(f"{DATA_DIR}/embeddings.npy"):
        raise RuntimeError("No embeddings on the volume yet. Run embed_all() first.")
    emb = np.load(f"{DATA_DIR}/embeddings.npy")
    with open(f"{DATA_DIR}/embedding_ids.json", encoding="utf-8") as f:
        ids = json.load(f)
    rows = {r["id"]: r for r in _read_companies()}
    _STATE.update(
        model=_load_model("cpu"),
        emb=emb,
        ids=ids,
        idx={cid: i for i, cid in enumerate(ids)},
        rows=rows,
        by_name={r["name"].strip().lower(): r["id"] for r in rows.values()},
        by_row={r["row_id"]: r["id"] for r in rows.values()},
        load_seconds=round(time.time() - t0, 2),
    )
    return _STATE


def _int_or_none(v: str):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _company_dict(row: dict) -> dict:
    """Company-shaped dict (see backend/app/models.py Company), plus a few extras."""
    return {
        "company_id": row["id"],
        "id": row["id"],
        "row_id": _int_or_none(row.get("row_id")),
        "name": row["name"],
        "one_liner": row.get("one_liner") or "",
        "sector": row.get("sector_label") or "",
        "sector_key": row.get("sector") or None,
        "stage": row.get("stage_label") or "",
        "country": row.get("country_label") or None,
        "founded": _int_or_none(row.get("founded_year")),
        "website": row.get("website") or None,
        "domain": row.get("domain") or None,
    }


def _resolve_company(query: str) -> str | None:
    """A query can be a company id, an exact name, or a row number like '#0193' / '193'."""
    s = _STATE
    q = query.strip()
    if q in s["idx"]:
        return q
    low = q.lower()
    if low in s["by_name"]:
        return s["by_name"][low]
    num = q.lstrip("#")
    if num.isdigit():
        cid = s["by_row"].get(str(int(num)))
        if cid:
            return cid
    return None


# ---------------------------------------------------------------------------
# Functions
# ---------------------------------------------------------------------------


@app.function(image=image, cpu=16.0, memory=16384, volumes={DATA_DIR: volume}, timeout=1800)
def embed_all(batch_size: int = 256) -> dict:
    """Embed the `text` field of every company, L2-normalise, save to the volume."""
    import json
    from datetime import datetime, timezone

    import numpy as np

    t0 = time.time()
    volume.reload()
    rows = _read_companies()
    ids = [r["id"] for r in rows]
    texts = [(r.get("text") or f'{r["name"]}. {r.get("one_liner", "")}').strip() for r in rows]
    model = _load_model("cpu")
    t_load = time.time() - t0

    t1 = time.time()
    emb = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    ).astype(np.float32)
    t_encode = time.time() - t1

    np.save(f"{DATA_DIR}/embeddings.npy", emb)
    with open(f"{DATA_DIR}/embedding_ids.json", "w", encoding="utf-8") as f:
        json.dump(ids, f)
    meta = {
        "model": EMBED_MODEL,
        "dim": int(emb.shape[1]),
        "count": int(emb.shape[0]),
        "load_seconds": round(t_load, 2),
        "encode_seconds": round(t_encode, 2),
        "total_seconds": round(time.time() - t0, 2),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(f"{DATA_DIR}/embed_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    volume.commit()
    return meta


@app.function(image=image, cpu=4.0, memory=8192, volumes={DATA_DIR: volume}, scaledown_window=600, timeout=120)
def similar_companies(query: str, k: int = 10, exclude_ids: list[str] | None = None) -> dict:
    """Companies most like `query` (free text, or a company id / exact name / row number).

    Returns {"query", "query_company": Company|None, "model", "results": [{company_id, name, sector, country, score, ...}]}.
    `score` is cosine similarity (0..1-ish). A company query never returns itself.
    """
    import numpy as np

    s = _state()
    k = max(1, min(int(k), 200))
    cid = _resolve_company(query)
    if cid is not None:
        qv = s["emb"][s["idx"][cid]]
    else:
        qv = s["model"].encode([QUERY_PREFIX + query.strip()], normalize_embeddings=True, convert_to_numpy=True)[0]
    scores = s["emb"] @ qv.astype(np.float32)

    skip = set(exclude_ids or [])
    if cid is not None:
        skip.add(cid)
    for sid in skip:
        i = s["idx"].get(sid)
        if i is not None:
            scores[i] = -np.inf

    top = np.argpartition(-scores, k)[:k]
    top = top[np.argsort(-scores[top])]
    results = []
    for i in top:
        row = s["rows"][s["ids"][i]]
        d = _company_dict(row)
        d["score"] = round(float(scores[i]), 4)
        results.append(d)
    return {
        "query": query,
        "query_company": _company_dict(s["rows"][cid]) if cid else None,
        "model": EMBED_MODEL,
        "results": results,
    }


def _universe():
    """fitcore.Universe over the stored embeddings (built once per container)."""
    s = _state()
    if "U" not in s:
        import fitcore

        s["U"] = fitcore.Universe(s["rows"], s["emb"], s["ids"])
    return s["U"]


def _embed(texts: list[str], query: bool):
    """Embed texts with the same model as embed_all(). `query=True` adds BGE's search prefix (thesis text)."""
    s = _state()
    texts = [(QUERY_PREFIX + t) if query else t for t in texts]
    return s["model"].encode(texts, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)


# Scales to zero: no min_containers anywhere. A warm container stays 10 min after the last call so the demo stays fast
# (8 CPU + 16 GB idle for 10 min is about $0.08); timeout covers a cold start (~20 s) plus scoring (~2 s) many times over.
@app.function(image=image, cpu=8.0, memory=16384, volumes={DATA_DIR: volume}, scaledown_window=600, timeout=300)
def score_fit(fund_dna: dict, portfolio: list, k: int = 50, fund_id: str | None = None) -> dict:
    """Rank all companies by how well they fit a fund. Per-fund logistic regression, trained on the fly.

    fund_dna:  FundDNA-shaped dict (summary, stage, geo, sectors[{name, share}], themes). Can be {}.
    portfolio: what the fund owns. Each item is a company id / name / website / "#0193", or a dict
               {name, website?, one_liner?|description?, sector?, country?, stage?, founded?}. Dataset rows are
               matched by id, website domain or name; a dict that is not in the dataset but has a description is
               embedded on the fly and still counts.
    Returns {fund_id, k, dataset_size, n_scored, model (str), feature_weights: [{label, share, color}],
             results: [Company fields + rank, fit (0-99), score (0..1 = fit / 100), logit (raw, ranking order),
                       parts: {"Like the portfolio": 0..1, "Right stage": .., "Right location": .., ...},
                       fit_parts: [{label, value}] (contract FitPart), like: closest portfolio company id | None,
                       contributions: [{feature, part, label, value (0..1), raw, impact}],
                       nearest_portfolio: [{company_id, name, score}]],
             portfolio: {matched, external, unmatched}, thesis_text,
             model_info: {method, n_positive, n_negative, coefficients, feature_weights, fit_note, never_used},
             score_seconds, total_seconds}.
    Current portfolio companies are never in the results.
    """
    import fitcore

    return fitcore.run_score_fit(_universe(), fund_dna or {}, list(portfolio or []), k, _embed, fund_id=fund_id)


def _read_json(name: str):
    import json

    with open(f"{DATA_DIR}/{name}", encoding="utf-8") as f:
        return json.load(f)


@app.function(image=image, cpu=8.0, memory=16384, volumes={DATA_DIR: volume}, scaledown_window=120, timeout=900)
def backtest(fund: str) -> dict:
    """Time-ordered backtest for one fund slug ("y-combinator", "european-commission", "localglobe", ...).

    Sort the fund's dated deals, hold out the last min(20, max(10, n // 3)) (under 25 dated deals ->
    enough_history false, the same rule as the backend), train only on deals dated before the first held-out one
    and rank every company that is not a training deal. Reports top-1/5/10% hits and recall@k vs TF-IDF keyword
    baselines (the strongest one, including one with the model's own sector/stage/location features) and random.
    Leakage rules: see fitcore.run_backtest.
    Writes /data/cache/backtest_{fund}.json and returns the Backtest-shaped dict (+ status, details).
    """
    import json
    import os

    import fitcore

    U = _universe()
    texts = [U.rows[i].get("text") or U.rows[i]["name"] for i in range(U.n)]
    out = fitcore.run_backtest(U, _read_json("investors.json"), _read_json("investor_index.json"), fund, _embed, texts)
    os.makedirs(f"{DATA_DIR}/cache", exist_ok=True)
    with open(f"{DATA_DIR}/cache/backtest_{out['fund_id']}.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    volume.commit()
    return out


@app.local_entrypoint()
def smoke():
    """Three free-text queries and one company-id query against the deployed-style function."""
    queries = [
        "AI triage for GP practices",
        "app that helps young people budget and save money",
        "carbon capture and climate tech for heavy industry",
    ]
    for q in queries:
        t = time.time()
        out = similar_companies.remote(q, 5)
        print(f"\n== {q!r}  ({time.time() - t:.2f}s)")
        for r in out["results"]:
            print(f'  {r["score"]:.3f}  {r["name"]:<32} {r["sector"]:<14} {r["country"] or "":<10} {r["one_liner"][:70]}')


# Example LocalGlobe portfolio for the smoke test (public, well-known holdings; the live run uses what the Reader
# agent scrapes from the fund's website). Three are in the dataset; the rest are embedded from their one-liners.
LOCALGLOBE_DNA = {
    "summary": "Backs very early founders in the UK and Europe, mostly fintech, health and deep tech.",
    "stage": "Pre-seed & Seed",
    "geo": "UK & Europe",
    "sectors": [{"name": "Fintech", "share": 0.33}, {"name": "Health", "share": 0.24},
                {"name": "Deep tech", "share": 0.21}, {"name": "Climate", "share": 0.14}],
    "themes": ["Very early UK and European founders", "Fintech for everyday money", "Health tools for the NHS",
               "Deep tech from universities"],
}
LOCALGLOBE_PORTFOLIO = [
    "Goodlord",
    "Nothing",
    "Deblock",
    {"name": "Cleo", "one_liner": "AI money assistant that helps young people budget, save and build credit",
     "country": "UK", "sector": "Fintech"},
    {"name": "Citymapper", "one_liner": "Public transport journey-planning app for big cities", "country": "UK",
     "sector": "Consumer"},
    {"name": "Wise", "one_liner": "Cheap international money transfers and multi-currency accounts", "country": "UK",
     "sector": "Fintech"},
    {"name": "Improbable", "one_liner": "Software for building large-scale virtual worlds and simulations",
     "country": "UK", "sector": "Deep tech"},
    {"name": "Lyst", "one_liner": "Online fashion shopping platform that brings thousands of brands into one place",
     "country": "UK", "sector": "Consumer"},
    {"name": "Bloom and Wild", "one_liner": "Online flower delivery with letterbox bouquets", "country": "UK",
     "sector": "Consumer"},
    {"name": "Tray.io", "one_liner": "Low-code platform to automate workflows and connect business apps",
     "country": "UK", "sector": "B2B SaaS"},
    {"name": "Zoopla", "one_liner": "UK property portal for buying, selling and renting homes", "country": "UK",
     "sector": "Proptech"},
]


@app.local_entrypoint()
def smoke_fit(k: int = 15):
    """score_fit for the example LocalGlobe portfolio. Prints the top k with their top reasons."""
    t = time.time()
    out = score_fit.remote(LOCALGLOBE_DNA, LOCALGLOBE_PORTFOLIO, k, "localglobe")
    print(f"score_fit: {time.time() - t:.2f}s round trip, {out['score_seconds']}s scoring, model={out['model']}")
    print("matched:", [m["name"] for m in out["portfolio"]["matched"]], "external:",
          [m["name"] for m in out["portfolio"]["external"]], "unmatched:", out["portfolio"]["unmatched"])
    print("weights:", [(w["label"], w["share"]) for w in out["feature_weights"]], "method:", out["model_info"]["method"])
    for r in out["results"]:
        reasons = "; ".join(c["label"] for c in r["contributions"][:3])
        print(f'  {r["fit"]:>3}  {r["name"][:30]:<30} {r["sector"]:<12} {r["country"] or "":<12} {reasons}')


@app.local_entrypoint()
def run_backtests(funds: str = "y-combinator,european-commission,bpifrance,localglobe"):
    """Run backtest() for each fund on Modal and save data/cache/backtest_{fund}.json locally for the backend."""
    import json
    from pathlib import Path

    cache = Path(__file__).resolve().parent.parent / "data" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    names = [f.strip() for f in funds.split(",") if f.strip()]
    for out in backtest.map(names, order_outputs=True):
        path = cache / f"backtest_{out['fund_id']}.json"
        path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        line = ", ".join(f"{m['label']} {m['found']}/{m['total']}" for m in out["methods"]) or out["status"]
        print(f"{out['fund_id']}: {line}  -> {path}")
