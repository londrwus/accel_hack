import json

from app import models


def test_page_endpoints_match_contract(client):
    for path, model in [
        ("/api/fund", models.FundResponse),
        ("/api/deals", models.DealsResponse),
        ("/api/portfolio", models.PortfolioResponse),
        ("/api/map", models.MapResponse),
        ("/api/memos", models.MemosResponse),
        ("/api/memos/northbeam-health", models.Memo),
        ("/api/universe", models.UniverseResponse),
        ("/api/companies/northbeam-health", models.Company),
        ("/api/runs/run_demo_localglobe", models.RunState),
    ]:
        r = client.get(path)
        assert r.status_code == 200, (path, r.text)
        model.model_validate(r.json())


def test_optional_fields_are_sent_as_null(client):
    company = client.get("/api/companies/ledgerly").json()
    assert "logo" in company and company["logo"] is None


def test_errors_are_plain_english(client):
    r = client.get("/api/memos/nope")
    assert r.status_code == 404 and r.json() == {"error": "There's no memo for this company yet."}
    r = client.get("/api/backtest", params={"fund_id": "no-such-fund"})  # the ML track may have written localglobe's
    assert r.status_code == 404 and r.json() == {"error": "No backtest yet for this fund"}
    assert client.get("/api/runs/nope").status_code == 404


def test_deals_filters_keep_counts(client):
    r = client.get("/api/deals", params={"status": "passed"}).json()
    assert {i["status"] for i in r["items"]} == {"passed"}
    assert r["counts"] == {"all": 61, "new": 3, "under_review": 12, "passed": 46}


def test_universe_search(client):
    r = client.get("/api/universe", params={"q": "triage"}).json()
    assert r["total"] == 1 and r["items"][0]["company"]["id"] == "northbeam-health"


def _read_sse(client, url, headers=None):
    events = []
    with client.stream("GET", url, headers=headers or {}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def test_demo_run_stream_and_reconnect(client):
    events = _read_sse(client, "/api/runs/run_demo_localglobe/events")
    assert len(events) == 47 and events[-1]["data"]["run_done"] is True
    newer = _read_sse(client, "/api/runs/run_demo_localglobe/events", {"Last-Event-ID": "40"})
    assert [e["seq"] for e in newer] == list(range(41, 48))


def test_new_run_replays_and_finishes(client):
    r = client.post("/api/runs?speed=100", json={"fund_url": "https://localglobe.vc", "force": True})
    assert r.status_code == 201
    run_id = r.json()["run_id"]
    assert r.json()["fund_id"] == "localglobe"
    events = _read_sse(client, f"/api/runs/{run_id}/events")
    assert events[-1]["agent"] == "Partner" and events[-1]["data"].get("run_done")
    state = client.get(f"/api/runs/{run_id}").json()
    assert state["status"] == "done"
    assert all(p["status"] == "done" for p in state["plan"])
    assert state["shortlist"][0]["company"]["id"] == "northbeam-health"


def test_feedback_sets_decision(client):
    r = client.post("/api/runs/run_demo_localglobe/feedback",
                    json={"company_id": "quay-health", "verdict": "meeting"})
    assert r.json() == {"ok": True}
    deals = client.get("/api/deals").json()
    quay = next(i for i in deals["items"] if i["company"]["id"] == "quay-health")
    assert quay["status"] == "under_review"
    assert deals["counts"]["passed"] == 45


def test_watch_simulate(client):
    r = client.post("/api/funds/localglobe/watch", json={"enabled": True, "simulate_next_run": True})
    body = r.json()
    assert body["watch"]["enabled"] is True and body["run_id"]
    assert client.get("/api/fund").json()["latest_run_id"] == body["run_id"]


def test_finished_run_has_no_agent_still_working(client):
    state = client.get("/api/runs/run_demo_localglobe").json()
    assert state["status"] == "done"
    assert all(a["status"] in ("done", "waiting") for a in state["agents"])


def test_settings_follow_env_file_edits(tmp_path, monkeypatch):
    from app import config

    env = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", env)
    for name in ("BW_TEST_KEY", "BW_TEST_MODE"):
        monkeypatch.delenv(name, raising=False)
        config._FROM_DOTENV.pop(name, None)
    assert config.setting("BW_TEST_KEY") is None
    env.write_text("BW_TEST_KEY=abc\nBW_TEST_MODE=replay\n", encoding="utf-8")
    assert config.setting("BW_TEST_KEY") == "abc"  # added to the .env: picked up without a restart
    assert config.setting("BW_TEST_MODE") == "replay"
    env.write_text("BW_TEST_MODE=live\n", encoding="utf-8")
    assert config.setting("BW_TEST_MODE") == "live"  # changed in the .env: picked up too
    assert config.setting("BW_TEST_KEY") is None  # removed from the .env: gone
    monkeypatch.setenv("BW_TEST_MODE", "")  # the shell wins, and empty means unset
    assert config.setting("BW_TEST_MODE", "replay") == "replay"
    for name in ("BW_TEST_KEY", "BW_TEST_MODE"):
        config._FROM_DOTENV.pop(name, None)


def test_map_views_and_centre(client):
    for q in ("", "?view=theme", "?view=new&limit=30", "?view=competition", "?view=theme&sector=Fintech&limit=50"):
        r = client.get("/api/map" + q)
        assert r.status_code == 200, (q, r.text)
        m = models.MapResponse.model_validate(r.json())
        ids = {n.id for n in m.nodes}
        assert all(e.source in ids and e.target in ids for e in m.edges), q
        assert m.note
    theme = models.MapResponse.model_validate(client.get("/api/map?view=theme").json())
    assert any(n.kind == "theme" for n in theme.nodes)
    centre = client.get("/api/map?center=northbeam-health&limit=12").json()
    assert centre["view"] == "center" and centre["center_id"] == "northbeam-health"
    assert all(e["label"] for e in centre["edges"])
    assert client.get("/api/map?view=nope").status_code in (400, 422)


def test_post_run_reuses_finished_run_unless_forced(client):
    r = client.post("/api/runs", json={"fund_url": "www.localglobe.vc/portfolio"})
    assert r.status_code == 201
    body = r.json()
    assert body["reused"] is True and body["fund_id"] == "localglobe"
    assert client.get(f"/api/runs/{body['run_id']}").json()["status"] == "done"
    forced = client.post("/api/runs?speed=100", json={"fund_url": "https://localglobe.vc", "force": True}).json()
    assert forced["reused"] is False and forced["run_id"] != body["run_id"]
