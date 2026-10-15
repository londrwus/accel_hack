"""Call the DEPLOYED Modal app exactly the way backend/app/modal_client.py does, and validate every answer
against backend/app/models.py. Needs only the `modal` package (+ pydantic, if installed, for the model checks).

Run from the repo root (PowerShell or bash), after `modal deploy` and `modal run modal_app.py::embed_all`:
    $env:PYTHONUTF8=1; python -I ml/check_deployed.py                  # checks only
    $env:PYTHONUTF8=1; python -I ml/check_deployed.py --save-backtests # also writes data/cache/backtest_{fund}.json

Exit code 0 = every check passed.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
APP = "bellwether"
FUNDS = ["y-combinator", "european-commission", "bpifrance", "localglobe"]
FIT_PARTS = {"Like the portfolio", "Right stage", "Right location", "Right sector", "Fits the thesis", "Founded recently"}
FAILS: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("  ok    " if ok else "  FAIL  ") + what)
    if not ok:
        FAILS.append(what)


def backend_models():
    try:
        spec = importlib.util.spec_from_file_location("bw_models", ROOT / "backend" / "app" / "models.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["bw_models"] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:  # no pydantic: structural checks only
        print(f"(backend models not loadable: {type(exc).__name__}; doing key checks only)")
        return None


M = backend_models()
COMPANY_KEYS = {"id", "row_id", "name", "one_liner", "sector", "stage", "country", "founded", "website"}


def valid_company(d: dict) -> bool:
    if M is not None:
        try:
            M.Company.model_validate(d)
            return True
        except Exception:
            return False
    return COMPANY_KEYS <= set(d) and all(isinstance(d[k], str) for k in ("id", "name", "one_liner", "sector", "stage"))


def brief(r: dict) -> dict:
    """Same shape as backend/app/tools/dataset.py brief(): what the agents send as a portfolio item."""
    return {"company_id": r["id"], "row_id": int(r["row_id"]), "name": r["name"], "one_liner": r["one_liner"][:200],
            "summary": r["summary"][:300] or None, "sector": r["sector_label"] or None,
            "country": r["country_label"] or None, "stage": r["stage_label"] or None,
            "founded": int(r["founded_year"]) if r["founded_year"] else None,
            "last_funding": r["last_funding_date"] or None, "website": r["domain"] or None}


def main() -> int:
    save = "--save-backtests" in sys.argv
    with open(ROOT / "data" / "companies.csv", encoding="utf-8", newline="") as f:
        rows = {r["name"]: r for r in csv.DictReader(f)}
    n_rows = len(rows)

    print("embeddings on the volume")
    try:
        vol = modal.Volume.from_name("bellwether-data")
        meta = json.loads(b"".join(vol.read_file("embed_meta.json")))
        check(meta.get("count") == n_rows and meta.get("dim") == 768, f"embed_meta {meta.get('model')} {meta.get('count')}x{meta.get('dim')}")
    except Exception as exc:
        check(False, f"embed_meta.json readable ({type(exc).__name__}: {exc})")

    print("similar_companies (free text)")
    fn = modal.Function.from_name(APP, "similar_companies")
    t = time.time()
    out = fn.remote("AI triage for GP practices", 10)
    print(f"  {time.time() - t:.1f}s")
    check(set(out) >= {"query", "query_company", "model", "results"}, "top-level keys")
    check(out["query_company"] is None, "free text has no query_company")
    check(0 < len(out["results"]) <= 10, f"{len(out['results'])} results")
    check(all(valid_company(r) and isinstance(r.get("score"), float) for r in out["results"]), "results are Company + score")
    print("   ", [r["name"] for r in out["results"][:5]])

    print("similar_companies (company id + exclude_ids, as the Mapper calls it)")
    qid = rows["Goodlord"]["id"]
    first = fn.remote(qid, 6)["results"]
    t = time.time()
    out = fn.remote(qid, 5, exclude_ids=[first[0]["id"]])
    print(f"  {time.time() - t:.1f}s (warm)")
    ids = [r["id"] for r in out["results"]]
    check(out["query_company"] and out["query_company"]["id"] == qid, "query_company is Goodlord")
    check(qid not in ids, "never returns the query company")
    check(first[0]["id"] not in ids, "exclude_ids respected")
    check(ids == [r["id"] for r in first[1:6]], "same order as without the excluded id")

    print("score_fit (positional args, like modal_client.score_fit)")
    dna = json.loads((ROOT / "frontend" / "src" / "mocks" / "fund.json").read_text(encoding="utf-8"))["fund"]["dna"]
    portfolio = [brief(rows[n]) for n in ("Goodlord", "Nothing", "Deblock")] + [
        {"name": "Cleo", "one_liner": "AI money assistant that helps young people budget and save", "country": "UK",
         "sector": "Fintech"}]
    t = time.time()
    out = modal.Function.from_name(APP, "score_fit").remote(dna, portfolio, 50)
    print(f"  {time.time() - t:.1f}s, scoring {out.get('score_seconds')}s")
    res = out.get("results") or []
    check(isinstance(out.get("model"), str) and out.get("n_scored") == n_rows, f"model={out.get('model')!r} n_scored={out.get('n_scored')}")
    check(len(res) == 50, f"{len(res)} results")
    check(all(valid_company(r) for r in res), "results are Company-shaped")
    check(all(isinstance(r["fit"], int) and 0 <= r["fit"] <= 99 for r in res), "fit is an int 0..99")
    check([r["fit"] for r in res] == sorted((r["fit"] for r in res), reverse=True), "best first")
    check(all(0 <= r["score"] <= 1 for r in res), "score is 0..1")
    check(all(set(r["parts"]) <= FIT_PARTS and all(0 <= v <= 1 for v in r["parts"].values()) for r in res),
          "parts: FitPart labels, values 0..1")
    check(all("Like the portfolio" in r["parts"] and "Right location" in r["parts"] for r in res),
          "parts has the design bars (Like the portfolio, Right location)")
    if M is not None:
        try:
            [M.FitPart.model_validate(p) for r in res for p in r["fit_parts"]]
            [M.FeatureWeight.model_validate(w) for w in out["feature_weights"]]
            check(True, "fit_parts / feature_weights validate")
        except Exception as exc:
            check(False, f"fit_parts / feature_weights validate ({exc})")
    check(abs(sum(w["share"] for w in out["feature_weights"]) - 1) < 0.011, "feature weight shares sum to 1")
    owned = {p["company_id"] for p in portfolio if "company_id" in p}
    check(not owned & {r["id"] for r in res}, "portfolio companies are never recommended")
    check(len(out["portfolio"]["matched"]) == 3 and len(out["portfolio"]["external"]) == 1, "3 matched + 1 external")
    for r in res[:5]:
        print(f'    {r["fit"]:>3} {r["name"][:30]:<30} {r["parts"]}')

    print("backtest (spawn + get, like modal_client.backtest)")
    bt_fn = modal.Function.from_name(APP, "backtest")
    calls = {f: bt_fn.spawn(f) for f in FUNDS}
    for f, fc in calls.items():
        t = time.time()
        bt = fc.get(timeout=900)
        ok = True
        if M is not None:
            try:
                M.Backtest.model_validate(bt)
            except Exception:
                ok = False
        check(ok, f"{f}: Backtest validates")
        if bt["enough_history"]:
            check(bt["held_out"] >= 10 and [m["label"] for m in bt["methods"]] ==
                  ["Bellwether model", "Keyword search", "Random pick"], f"{f}: held_out {bt['held_out']}, 3 methods")
            print("   ", f, ", ".join(f"{m['label']} {m['found']}/{m['total']}" for m in bt["methods"]),
                  "| profile-only:", (bt["details"]["metrics"]["website_profile_only"]["model"] or {}).get("top_5pct"))
        else:
            print("   ", f, bt["details"]["message"])
        if save:
            path = ROOT / "data" / "cache" / f"backtest_{bt['fund_id']}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(bt, indent=2), encoding="utf-8")
            print("    saved", path)

    print(f"\n{len(FAILS)} failed" + (": " + "; ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except modal.exception.NotFoundError as exc:
        print(f"\nThe app '{APP}' is not deployed (or a function is missing): {exc}")
        print("Deploy first: cd ml; modal deploy modal_app.py; modal run modal_app.py::embed_all")
        sys.exit(2)
