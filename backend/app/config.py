"""Paths and settings.

Settings are read from the process environment first, then from the repo-root `.env`.
The `.env` file is re-read on every call, so adding ANTHROPIC_API_KEY (or switching
DEMO_MODE) takes effect on the next run without restarting the server.

A variable set in the real process environment always wins, even when it is empty:
`ANTHROPIC_API_KEY= DEMO_MODE=live uvicorn ...` runs with no key whatever the .env says.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
ENV_FILE = REPO_ROOT / ".env"

# Overridable for hosted deploys (Modal mounts a volume at /data).
DATA_DIR = Path(os.environ.get("BELLWETHER_DATA_DIR") or (REPO_ROOT / "data"))
CACHE_DIR = Path(os.environ.get("BELLWETHER_CACHE_DIR") or (DATA_DIR / "cache"))
REPLAY_DIR = CACHE_DIR / "replay"
MOCKS_DIR = Path(os.environ.get("BELLWETHER_MOCKS_DIR") or (REPO_ROOT / "frontend" / "src" / "mocks"))

DEMO_RUN_ID = "run_demo_localglobe"
CORS_ORIGINS = [o.strip() for o in (os.environ.get("CORS_ORIGINS")
                or "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
# Regex for extra allowed origins (default: any Vercel deployment).
CORS_ORIGIN_REGEX = os.environ.get("CORS_ORIGIN_REGEX", r"https://.*\.vercel\.app")


def _read_env_file() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    return {k: v for k, v in dotenv_values(ENV_FILE).items() if v is not None}


# Values this module copied from the .env into os.environ (so SDKs that read os.environ see them).
# Anything else in os.environ was set by the shell or a test and always wins.
_FROM_DOTENV: dict[str, str] = {}
for _k, _v in _read_env_file().items():
    if _k not in os.environ:
        os.environ[_k] = _v
        _FROM_DOTENV[_k] = _v


def setting(name: str, default: str | None = None) -> str | None:
    """Process env wins (an empty value counts as "unset"); otherwise the current .env contents.

    The .env is re-read on every call, so editing it (adding the key, switching DEMO_MODE) works
    without a restart.
    """
    current = os.environ.get(name)
    if current is not None and _FROM_DOTENV.get(name) != current:
        return current or default  # set by the shell or a test
    value = _read_env_file().get(name)
    if value:
        os.environ[name] = _FROM_DOTENV[name] = value
        return value
    if name in _FROM_DOTENV:  # removed from the .env since we loaded it
        os.environ.pop(name, None)
        _FROM_DOTENV.pop(name, None)
    return default


def demo_mode() -> str:
    """`replay` (default) or `live`."""
    mode = (setting("DEMO_MODE", "replay") or "replay").strip().lower()
    return mode if mode in ("replay", "live") else "replay"


def anthropic_key() -> str | None:
    return setting("ANTHROPIC_API_KEY")


def live_ready() -> bool:
    """True when a run would use the live agent team."""
    return demo_mode() == "live" and bool(llm_key())


def default_fund_id() -> str:
    return setting("DEFAULT_FUND", "localglobe") or "localglobe"


def db_path() -> Path:
    return Path(setting("BELLWETHER_DB", str(BACKEND_DIR / "bellwether.db")))


def companies_csv() -> Path:
    return Path(setting("COMPANIES_CSV", str(DATA_DIR / "companies.csv")))


def replay_speed() -> float:
    try:
        return max(0.01, float(setting("REPLAY_SPEED", "1") or "1"))
    except ValueError:
        return 1.0


def modal_timeout_s() -> float:
    try:
        return float(setting("MODAL_TIMEOUT_S", "20") or "20")
    except ValueError:
        return 20.0


# ---------------------------------------------------------------------------
# Run profile: how much work a live run does (RUN_PROFILE=fast | thorough, default fast)
# ---------------------------------------------------------------------------

PROFILES: dict[str, dict[str, float]] = {
    # fast: about 90s to a finished memo. thorough: the earlier, slower settings (~4 minutes).
    "fast": {
        "rerank_pool": 60,          # candidates the second judge (Jev) reads
        "rerank_deadline_s": 15,    # Jev rerank gives up after this
        "consider": 20,             # candidates Deal Finder reads closely
        "rank_batch": 5,            # candidates per parallel close-read call (0 = one call for all)
        "rank_max_tokens": 3000,
        "market_max_uses": 3,       # web searches in the news check
        "market_articles": 15,      # news results kept
        "market_cap_s": 25,         # the news search gives up after this (it runs in the background; nothing waits on it)
        "market_wait_s": 8,         # how long the memo waits for late news
        "analyst_max_uses": 2,
        "analyst_hits": 4,
        "analyst_max_tokens": 4000,
        "critic_effort_low": 1,
        "critic_max_tokens": 4000,
        "mapper_concurrency": 6,
        "thinking": 0,              # extended thinking off: the biggest single speed-up (Haiku answers ~8x faster)
        "enrich_concurrency": 4,    # Enricher companies in flight (each opens 2 pages): keeps the deal search fast
        "enrich_wait_s": 0,         # the end of the run does not wait for the Enricher (it carries on afterwards)
        "analyst_site_s": 12,       # the Analyst stops waiting for a slow company website after this
    },
    "thorough": {
        "rerank_pool": 150, "rerank_deadline_s": 45, "consider": 50, "rank_batch": 0, "rank_max_tokens": 16000,
        "market_max_uses": 5, "market_articles": 20, "market_cap_s": 120, "market_wait_s": 120,
        "analyst_max_uses": 3, "analyst_hits": 5, "analyst_max_tokens": 16000, "critic_effort_low": 0,
        "critic_max_tokens": 16000, "mapper_concurrency": 1, "thinking": 1,
        "enrich_concurrency": 16, "enrich_wait_s": 45, "analyst_site_s": 120,
    },
}


def run_profile() -> str:
    p = (setting("RUN_PROFILE", "fast") or "fast").strip().lower()
    return p if p in PROFILES else "fast"


def cap(name: str) -> int:
    """A limit from the current run profile, e.g. cap("consider")."""
    return int(PROFILES[run_profile()][name])


def modal_app_name() -> str:
    return setting("MODAL_APP", "bellwether") or "bellwether"


# ---------------------------------------------------------------------------
# Model provider and models per role
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "claude-haiku-5-5"


def llm_provider() -> str:
    """`anthropic` (default) or `deepseek` (same Anthropic SDK, pointed at DEEPSEEK_BASE_URL)."""
    p = (setting("LLM_PROVIDER", "anthropic") or "anthropic").strip().lower()
    return p if p in ("anthropic", "deepseek") else "anthropic"


def llm_key() -> str | None:
    """The API key for the active provider."""
    if llm_provider() == "deepseek":
        return setting("DEEPSEEK_API_KEY")
    return anthropic_key()


def deepseek_base_url() -> str:
    return setting("DEEPSEEK_BASE_URL", "https://api.deepseek.com/anthropic") or "https://api.deepseek.com/anthropic"


def model_for(role: str) -> str:
    """The model id for a role: `orchestrator`, `worker` or `extract`.

    Read from MODEL_ORCHESTRATOR / MODEL_WORKER / MODEL_EXTRACT (default claude-haiku-5-5). With
    LLM_PROVIDER=deepseek, DEEPSEEK_MODEL (default deepseek-chat) is used for every role unless the role's
    own variable names a non-Claude model.
    """
    name = setting(f"MODEL_{role.upper()}", DEFAULT_MODEL) or DEFAULT_MODEL
    if llm_provider() == "deepseek" and name.startswith("claude-"):
        return setting("DEEPSEEK_MODEL", "deepseek-chat") or "deepseek-chat"
    return name


# ---------------------------------------------------------------------------
# Jev (TypeSafe System One) via the Jev Gateway
# ---------------------------------------------------------------------------


def jev_key() -> str | None:
    return setting("JEV_API_KEY")


def jev_base_url() -> str:
    return (setting("JEV_BASE_URL", "https://jevgate.io") or "https://jevgate.io").rstrip("/")


def jev_model() -> str:
    return setting("JEV_MODEL", "jev-latest") or "jev-latest"


def jev_timeout_s() -> float:
    try:
        return float(setting("JEV_TIMEOUT_S", "10") or "10")
    except ValueError:
        return 10.0
