import os
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="bellwether-test-"))
os.environ["BELLWETHER_DB"] = str(_tmp / "test.db")
os.environ["DEMO_MODE"] = "replay"
os.environ["ANTHROPIC_API_KEY"] = ""  # never make paid calls from tests, whatever the .env holds
os.environ["LLM_PROVIDER"] = "anthropic"
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["JEV_API_KEY"] = ""  # Jev is faked per test (tests/fakes.py FakeJev)
for _role in ("ORCHESTRATOR", "WORKER", "EXTRACT"):
    os.environ[f"MODEL_{_role}"] = ""  # the default (claude-haiku-5-5) unless a test sets one
os.environ.setdefault("COMPANIES_CSV", str(_tmp / "missing.csv"))  # use the mock universe
os.environ["MODAL_DISABLED"] = "1"  # never call Modal from tests; test_modal_client.py fakes it
os.environ["INVESTOR_INDEX_JSON"] = str(_tmp / "missing_index.json")  # "can't tell" -> 404 backtest
os.environ["INVESTORS_JSON"] = str(_tmp / "missing_investors.json")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
