import asyncio
import json

import pytest

from app import config, data, modal_client as mc, store


class NotFoundError(Exception):  # same name as modal.exception.NotFoundError
    pass


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    mc.reset_status()
    yield
    mc.reset_status()


@pytest.fixture
def modal_on(monkeypatch):
    monkeypatch.setattr(mc, "configured", lambda: True)
    return monkeypatch


def run(coro):
    return asyncio.run(coro)


def test_no_token_uses_offline_fallback_shaped_like_modal():
    r = run(mc.similar_companies("AI triage for GP practices", k=5))
    assert r.source == "fallback" and r.reason == "Modal is switched off."
    assert set(r.value) == {"query", "query_company", "model", "results"}
    assert r.value["results"][0]["id"] == "northbeam-health"
    assert {"id", "company_id", "row_id", "name", "score"} <= set(r.value["results"][0])


def test_success_is_cached_then_used_when_modal_fails(modal_on):
    answer = {"query": "x", "query_company": None, "model": "bge", "results": [{"id": "a", "score": 0.9}]}

    async def ok(fn, *a, **k):
        return answer

    modal_on.setattr(mc, "_remote", ok)
    r = run(mc.similar_companies("seaweed carbon", k=3))
    assert r.source == "modal" and r.value == answer
    assert list((config.CACHE_DIR / "modal").glob("similar_companies__seaweed-carbon__*.json"))

    async def missing(fn, *a, **k):
        raise NotFoundError("App 'bellwether' not found")

    mc.reset_status()
    modal_on.setattr(mc, "_remote", missing)
    r = run(mc.similar_companies("seaweed carbon", k=3))
    assert r.source == "cache" and r.value == answer and "isn't deployed" in r.reason
    # the app is known to be missing: the next call skips Modal straight away
    r = run(mc.similar_companies("something new", k=3))
    assert r.source == "fallback" and "isn't deployed" in r.reason


def test_slow_modal_times_out_fast(modal_on):
    async def slow(fn, *a, **k):
        await asyncio.sleep(10)

    modal_on.setattr(mc, "_remote", slow)
    r = run(mc.call("score_fit", {}, [], 5, timeout=0.05, fallback=lambda: {"results": []}))
    assert r.source == "fallback" and "too long" in r.reason and r.seconds < 2


def test_tools_wrapper_keeps_old_contract():
    from app.tools import modal_client as old

    value, used_fallback = run(old.call("score_fit", {}, [], 5, fallback={"cached": True}))
    assert value == {"cached": True} and used_fallback is True


def test_score_fit_offline_shape():
    dna = data.mock("fund").fund.dna.model_dump()
    r = run(mc.score_fit(dna, [{"name": "Cleo", "one_liner": "AI money coach"}], 5, fund_id="localglobe"))
    assert r.source == "fallback"
    assert {"model", "n_scored", "score_seconds", "feature_weights", "results"} <= set(r.value)
    top = r.value["results"][0]
    assert 0 <= top["fit"] <= 100 and {"label", "value"} <= set(top["fit_parts"][0])


def test_score_fit_modal_scores_saved(client, modal_on):
    dna = data.mock("fund").fund.dna.model_dump()

    async def ok(fn, *a, **k):
        return {"model": "lr", "n_scored": 3, "score_seconds": 1.0, "feature_weights": [],
                "results": [{"id": "x", "row_id": 7, "fit": 88, "score": 0.88, "fit_parts": []}]}

    modal_on.setattr(mc, "_remote", ok)
    r = run(mc.score_fit(dna, ["cleo"], 10, fund_id="testfund"))
    assert r.source == "modal" and store.get_memory("testfund", "scores") == {"7": 88}


def _index(tmp_path, monkeypatch, dated):
    p = tmp_path / "index.json"
    p.write_text(json.dumps({"investors": {}, "fund_families": {"somefund": {"dated_any": dated}}}))
    monkeypatch.setenv("INVESTOR_INDEX_JSON", str(p))


def test_backtest_not_enough_history(client, tmp_path, monkeypatch):
    _index(tmp_path, monkeypatch, 3)
    r = client.get("/api/backtest", params={"fund_id": "somefund"})
    assert r.status_code == 200
    body = r.json()
    assert body["enough_history"] is False and body["methods"] == [] and body["feature_weights"] == []


def _backtest(held_out):
    bt = json.loads((config.MOCKS_DIR / "backtest.json").read_text(encoding="utf-8"))
    bt.update(fund_id="somefund", held_out=held_out)
    for fw in bt["feature_weights"]:
        fw.pop("color")  # the backend fills colours in
    return bt


def test_backtest_runs_on_modal_and_is_saved(client, tmp_path, modal_on):
    _index(tmp_path, modal_on, 300)
    polls = iter([TimeoutError(), _backtest(20)])

    async def spawn(fund):
        return object()

    async def poll(fc, wait):
        item = next(polls)
        if isinstance(item, Exception):
            raise item
        return item

    modal_on.setattr(mc, "_spawn_backtest", spawn)
    modal_on.setattr(mc, "_poll_call", poll)
    r = client.get("/api/backtest", params={"fund_id": "somefund"})
    assert r.status_code == 404  # still running on Modal
    r = client.get("/api/backtest", params={"fund_id": "somefund"})
    assert r.status_code == 200 and r.json()["enough_history"] is True
    assert r.json()["feature_weights"][0]["color"].startswith("#")
    assert (config.CACHE_DIR / "backtest_somefund.json").exists()


def test_backtest_with_few_held_out_has_no_numbers(tmp_path, modal_on):
    _index(tmp_path, modal_on, 300)

    async def spawn(fund):
        return object()

    async def poll(fc, wait):
        return _backtest(4)

    modal_on.setattr(mc, "_spawn_backtest", spawn)
    modal_on.setattr(mc, "_poll_call", poll)
    r = run(mc.backtest("somefund"))
    assert r.value["enough_history"] is False and r.value["methods"] == []


def test_universe_search_uses_model_ranking(client, tmp_path, modal_on):
    csv_path = tmp_path / "companies.csv"
    csv_path.write_text(
        "row_id,id,name,one_liner,sector_label,stage_label,country_label,founded_year,domain\n"
        "1,quill,Quill,Notes for doctors,Health,Seed,UK,2023,quill.io\n"
        "2,medibot,Medibot,Chat assistant for clinics,Health,Seed,UK,2022,\n"
        "3,farmly,Farmly,Tractor rental,Agritech,Seed,France,2021,\n",
        encoding="utf-8")
    modal_on.setenv("COMPANIES_CSV", str(csv_path))
    data._csv_rows.cache_clear()

    async def ok(fn, query, k, **kw):
        return {"query": query, "query_company": None, "model": "bge",
                "results": [{"id": "medibot", "score": 0.8}, {"id": "quill", "score": 0.7}]}

    modal_on.setattr(mc, "_remote", ok)
    try:
        r = client.get("/api/universe", params={"q": "doctors"}).json()
        ids = [i["company"]["id"] for i in r["items"]]
        assert ids == ["medibot", "quill"]  # Medibot has no word "doctors": found by meaning
    finally:
        data._csv_rows.cache_clear()


def test_health_reports_modal_and_anthropic(client):
    h = client.get("/api/health").json()
    assert h["modal"] == "fallback" and h["anthropic"] in ("key present", "no key")
    assert set(h["modal_functions"]) == set(mc.FUNCTIONS) and h["demo_mode"] == "replay"
