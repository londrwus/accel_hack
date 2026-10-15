"""Ask the team: routing, parallel personas, a cited answer, events in the feed, saved history. Mocked LLM."""

from __future__ import annotations

import asyncio

from app import runs, store
from app.agents import ask
from app.agents.llm import LLM
from app.models import AgentEvent
from tests.fakes import FakeAnthropic


def _llm(personas=("Market", "Mapper")):
    fake = FakeAnthropic({
        "AskRoute": {"personas": list(personas), "note": "Market checks the news; Mapper checks rivals."},
        "AskAnswerDraft": {"answer": "Rival Pay competes with Alpha Pay [1]. Funding unclear [9].",
                           "source_numbers": [1], "company_ids": ["not-a-company"], "unsure": False},
    })
    return LLM(client=fake), fake


def _run():
    store.init_db()
    run = store.create_run(runs.new_run_id("testfund"), "testfund", "https://testfund.vc", "t", "live",
                           status="done")
    runs.Emitter(run["id"]).done("Partner", "Done.", run_done=True)
    return run


def test_answer_question_streams_and_persists():
    run = _run()
    q = store.add_question("q_test1", run["id"], "testfund", "Who are Alpha Pay's competitors?")
    llm, fake = _llm()
    out = asyncio.run(ask.answer_question(run["id"], q["id"], llm=llm))
    assert out["status"] == "answered"
    assert out["personas"] == ["Market", "Mapper"]
    assert "[1]" in out["answer"] and "[9]" not in out["answer"]  # invalid citation dropped
    assert out["sources"] and out["sources"][0]["url"].startswith("https://news.test")
    assert out["company_ids"] == []  # unknown ids are filtered out
    evs = [AgentEvent.model_validate(e) for e in store.get_events(run["id"])]
    mine = [e for e in evs if e.data.get("question_id") == "q_test1"]
    assert {e.agent for e in mine} >= {"Partner", "Market", "Mapper"}
    assert all(e.tag == "Question" for e in mine if e.type != "done")
    assert mine[-1].type == "answer" and mine[-1].data["answer"] == out["answer"]
    assert not store.get_run(run["id"])["state"].get("asking")
    assert store.list_questions("testfund")[-1]["id"] == "q_test1"


def test_failed_llm_gives_plain_answer():
    run = _run()
    q = store.add_question("q_test2", run["id"], "testfund", "What changed?")
    fake = FakeAnthropic({"AskRoute": RuntimeError("boom")})
    out = asyncio.run(ask.answer_question(run["id"], q["id"], llm=LLM(client=fake)))
    assert out["status"] == "error" and out["answer"]
    assert store.get_events(run["id"])[-1]["type"] == "answer"


def test_ask_endpoints(client, monkeypatch):
    llm, _ = _llm(("Thesis",))
    monkeypatch.setattr(ask, "_llm_factory", lambda: llm)
    monkeypatch.setattr(ask.config, "llm_key", lambda: "sk-test")
    run = _run()
    r = client.post(f"/api/runs/{run['id']}/ask", json={"question": "What does this fund invest in?"})
    assert r.status_code == 202, r.text
    qid = r.json()["question_id"]
    for _ in range(50):
        item = client.get(f"/api/questions/{qid}").json()
        if item["status"] != "working":
            break
        asyncio.run(asyncio.sleep(0.05))
    assert item["status"] == "answered", item
    hist = client.get("/api/funds/testfund/questions").json()["items"]
    assert any(h["id"] == qid for h in hist)
    assert client.post("/api/runs/nope/ask", json={"question": "x"}).status_code == 404
    assert client.post(f"/api/runs/{run['id']}/ask", json={"question": "  "}).status_code == 422
