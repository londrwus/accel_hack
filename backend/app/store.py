"""SQLite store: runs, events, memory, feedback, watch.

One file (backend/bellwether.db), one short-lived connection per call, a process-wide lock
for writes. Safe to call from async code and from worker threads. Plain dicts in and out.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from . import config

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    fund_id     TEXT NOT NULL,
    fund_url    TEXT NOT NULL,
    task        TEXT NOT NULL,
    mode        TEXT NOT NULL,            -- replay | live
    status      TEXT NOT NULL,            -- running | done | error
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    state       TEXT NOT NULL DEFAULT '{}' -- JSON: partner_summary, since_last_run, replay_pos, ...
);
CREATE INDEX IF NOT EXISTS runs_fund ON runs(fund_id, started_at);

CREATE TABLE IF NOT EXISTS events (
    run_id    TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    ts        TEXT NOT NULL,
    elapsed_s REAL NOT NULL,
    agent     TEXT NOT NULL,
    type      TEXT NOT NULL,
    message   TEXT NOT NULL,
    tag       TEXT,
    data      TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (run_id, seq)
);

CREATE TABLE IF NOT EXISTS memory (
    fund_id    TEXT NOT NULL,
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,              -- JSON
    updated_at TEXT NOT NULL,
    PRIMARY KEY (fund_id, key)
);

CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    fund_id    TEXT NOT NULL,
    company_id TEXT NOT NULL,
    verdict    TEXT NOT NULL,
    note       TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watch (
    fund_id     TEXT PRIMARY KEY,
    enabled     INTEGER NOT NULL,
    next_run_at TEXT,
    updated_at  TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    config.db_path().parent.mkdir(parents=True, exist_ok=True)
    with _lock, connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


def _run_row(row: sqlite3.Row | None) -> Optional[dict]:
    if row is None:
        return None
    d = dict(row)
    d["state"] = json.loads(d["state"] or "{}")
    return d


def create_run(run_id: str, fund_id: str, fund_url: str, task: str, mode: str,
               status: str = "running", started_at: str | None = None,
               state: dict | None = None) -> dict:
    with _lock, connect() as c:
        c.execute(
            "INSERT INTO runs (id, fund_id, fund_url, task, mode, status, started_at, state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, fund_id, fund_url, task, mode, status, started_at or now_iso(),
             json.dumps(state or {})),
        )
    return get_run(run_id)  # type: ignore[return-value]


def get_run(run_id: str) -> Optional[dict]:
    with connect() as c:
        return _run_row(c.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone())


def list_runs(fund_id: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
    q, args = "SELECT * FROM runs WHERE 1=1", []
    if fund_id:
        q += " AND fund_id = ?"
        args.append(fund_id)
    if status:
        q += " AND status = ?"
        args.append(status)
    q += " ORDER BY started_at DESC, rowid DESC LIMIT ?"
    args.append(limit)
    with connect() as c:
        return [_run_row(r) for r in c.execute(q, args).fetchall()]  # type: ignore[misc]


def latest_run(fund_id: str) -> Optional[dict]:
    runs = list_runs(fund_id=fund_id, limit=1)
    return runs[0] if runs else None


def set_run_status(run_id: str, status: str) -> None:
    finished = now_iso() if status in ("done", "error") else None
    with _lock, connect() as c:
        c.execute("UPDATE runs SET status = ?, finished_at = COALESCE(?, finished_at) WHERE id = ?",
                  (status, finished, run_id))


def update_run_state(run_id: str, **fields: Any) -> dict:
    """Merge fields into runs.state (JSON). Returns the new state."""
    with _lock, connect() as c:
        row = c.execute("SELECT state FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        state = json.loads(row["state"] or "{}")
        state.update(fields)
        c.execute("UPDATE runs SET state = ? WHERE id = ?", (json.dumps(state), run_id))
    return state


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


def _event_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["data"] = json.loads(d["data"] or "{}")
    return d


def append_event(run_id: str, *, agent: str, type: str, message: str, tag: str | None = None,
                 data: dict | None = None, ts: str | None = None,
                 elapsed_s: float | None = None) -> dict:
    """Insert the next event of a run (seq = last + 1) and return it as a dict.

    elapsed_s defaults to seconds since the run's started_at.
    """
    with _lock, connect() as c:
        run = c.execute("SELECT started_at FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            raise KeyError(run_id)
        seq = c.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id = ?",
                        (run_id,)).fetchone()[0]
        ts = ts or now_iso()
        if elapsed_s is None:
            started = datetime.fromisoformat(run["started_at"].replace("Z", "+00:00"))
            elapsed_s = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
        event = {"seq": seq, "ts": ts, "elapsed_s": float(elapsed_s), "run_id": run_id,
                 "agent": agent, "type": type, "message": message, "tag": tag,
                 "data": data or {}}
        c.execute(
            "INSERT INTO events (run_id, seq, ts, elapsed_s, agent, type, message, tag, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, seq, ts, event["elapsed_s"], agent, type, message, tag,
             json.dumps(event["data"], ensure_ascii=False)),
        )
    return event


def get_events(run_id: str, after_seq: int = 0) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT run_id, seq, ts, elapsed_s, agent, type, message, tag, data FROM events "
            "WHERE run_id = ? AND seq > ? ORDER BY seq", (run_id, after_seq)).fetchall()
    return [_event_row(r) for r in rows]


def count_events(run_id: str) -> int:
    with connect() as c:
        return c.execute("SELECT COUNT(*) FROM events WHERE run_id = ?", (run_id,)).fetchone()[0]


# ---------------------------------------------------------------------------
# memory (per fund key/value, JSON values)
# ---------------------------------------------------------------------------


def set_memory(fund_id: str, key: str, value: Any) -> None:
    with _lock, connect() as c:
        c.execute(
            "INSERT INTO memory (fund_id, key, value, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(fund_id, key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (fund_id, key, json.dumps(value, ensure_ascii=False), now_iso()),
        )


def get_memory(fund_id: str, key: str, default: Any = None) -> Any:
    with connect() as c:
        row = c.execute("SELECT value FROM memory WHERE fund_id = ? AND key = ?",
                        (fund_id, key)).fetchone()
    return json.loads(row["value"]) if row else default


def list_memory(fund_id: str, prefix: str = "") -> dict[str, Any]:
    with connect() as c:
        rows = c.execute("SELECT key, value FROM memory WHERE fund_id = ? AND key LIKE ?",
                         (fund_id, prefix + "%")).fetchall()
    return {r["key"]: json.loads(r["value"]) for r in rows}


def delete_fund_data(fund_id: str) -> None:
    """'Delete fund data' (RESPONSIBLE_AI.md): wipe memory, feedback, watch and runs for a fund."""
    with _lock, connect() as c:
        run_ids = [r[0] for r in c.execute("SELECT id FROM runs WHERE fund_id = ?", (fund_id,))]
        c.executemany("DELETE FROM events WHERE run_id = ?", [(r,) for r in run_ids])
        for table in ("runs", "memory", "feedback", "watch"):
            c.execute(f"DELETE FROM {table} WHERE fund_id = ?", (fund_id,))
        c.execute(_QUESTIONS_SQL)
        c.execute("DELETE FROM questions WHERE fund_id = ?", (fund_id,))


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------


def add_feedback(run_id: str, fund_id: str, company_id: str, verdict: str,
                 note: str | None = None) -> int:
    with _lock, connect() as c:
        cur = c.execute(
            "INSERT INTO feedback (run_id, fund_id, company_id, verdict, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)", (run_id, fund_id, company_id, verdict, note, now_iso()))
        return int(cur.lastrowid)


def list_feedback(fund_id: str) -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM feedback WHERE fund_id = ? ORDER BY id", (fund_id,)).fetchall()]


def latest_decisions(fund_id: str) -> dict[str, str]:
    """company_id -> the most recent verdict for that company."""
    return {f["company_id"]: f["verdict"] for f in list_feedback(fund_id)}


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------


def set_watch(fund_id: str, enabled: bool, next_run_at: str | None) -> dict:
    with _lock, connect() as c:
        c.execute(
            "INSERT INTO watch (fund_id, enabled, next_run_at, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(fund_id) DO UPDATE SET enabled = excluded.enabled, "
            "next_run_at = excluded.next_run_at, updated_at = excluded.updated_at",
            (fund_id, int(enabled), next_run_at, now_iso()))
    return get_watch(fund_id)  # type: ignore[return-value]


def get_watch(fund_id: str) -> Optional[dict]:
    with connect() as c:
        row = c.execute("SELECT * FROM watch WHERE fund_id = ?", (fund_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["enabled"] = bool(d["enabled"])
    return d


def list_watches(enabled_only: bool = True) -> list[dict]:
    q = "SELECT * FROM watch" + (" WHERE enabled = 1" if enabled_only else "")
    with connect() as c:
        rows = c.execute(q).fetchall()
    return [{**dict(r), "enabled": bool(r["enabled"])} for r in rows]


def funds_with_results() -> set[str]:
    """Fund ids that have a saved page or Universe scores (for GET /api/funds)."""
    with connect() as c:
        rows = c.execute("SELECT DISTINCT fund_id FROM memory WHERE key LIKE 'page:%' "
                         "OR key = 'scores' OR key LIKE 'memo:%'").fetchall()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# questions ("Ask the team" chat on /research)
# ---------------------------------------------------------------------------

_QUESTIONS_SQL = """CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, fund_id TEXT NOT NULL, question TEXT NOT NULL,
    status TEXT NOT NULL, personas TEXT NOT NULL DEFAULT '[]', answer TEXT, sources TEXT NOT NULL DEFAULT '[]',
    company_ids TEXT NOT NULL DEFAULT '[]', unsure INTEGER NOT NULL DEFAULT 0, asked_at TEXT NOT NULL,
    answered_at TEXT)"""


def _q_row(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("personas", "sources", "company_ids"):
        d[k] = json.loads(d[k] or "[]")
    d["unsure"] = bool(d["unsure"])
    return d


def add_question(qid: str, run_id: str, fund_id: str, question: str) -> dict:
    with _lock, connect() as c:
        c.execute(_QUESTIONS_SQL)
        c.execute("INSERT INTO questions (id, run_id, fund_id, question, status, asked_at) VALUES (?, ?, ?, ?, ?, ?)",
                  (qid, run_id, fund_id, question, "working", now_iso()))
    return get_question(qid)  # type: ignore[return-value]


def update_question(qid: str, **fields: Any) -> None:
    if not fields:
        return
    for k in ("personas", "sources", "company_ids"):
        if k in fields:
            fields[k] = json.dumps(fields[k], ensure_ascii=False)
    if "unsure" in fields:
        fields["unsure"] = int(bool(fields["unsure"]))
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _lock, connect() as c:
        c.execute(_QUESTIONS_SQL)
        c.execute(f"UPDATE questions SET {cols} WHERE id = ?", (*fields.values(), qid))


def get_question(qid: str) -> Optional[dict]:
    with connect() as c:
        c.execute(_QUESTIONS_SQL)
        row = c.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
    return _q_row(row) if row else None


def list_questions(fund_id: str, limit: int = 100) -> list[dict]:
    with connect() as c:
        c.execute(_QUESTIONS_SQL)
        rows = c.execute("SELECT * FROM questions WHERE fund_id = ? ORDER BY asked_at, rowid LIMIT ?",
                         (fund_id, limit)).fetchall()
    return [_q_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Writes clear the rendered-page cache (app.page_cache)
# ---------------------------------------------------------------------------


def _invalidating(fn):
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        finally:
            from . import page_cache
            page_cache.clear()
    return wrapper


for _name in ("set_memory", "delete_fund_data", "add_feedback", "set_watch", "create_run"):
    globals()[_name] = _invalidating(globals()[_name])
