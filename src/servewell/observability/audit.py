"""Append-only audit trail: every agent step, LLM call, guardrail result and action."""

import json
import sqlite3
from datetime import datetime

from servewell.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, run_id TEXT, ticket_id TEXT,
    event TEXT, actor TEXT, latency_ms INTEGER, detail TEXT
);
"""


def _con() -> sqlite3.Connection:
    s = get_settings()
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(s.audit_db)
    con.executescript(SCHEMA)
    return con


def log(run_id: str, ticket_id: str, event: str, detail: dict | str | None = None,
        actor: str = "agent", latency_ms: int | None = None) -> None:
    with _con() as con:
        con.execute(
            "INSERT INTO audit (ts, run_id, ticket_id, event, actor, latency_ms, detail) VALUES (?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), run_id, ticket_id, event, actor, latency_ms,
             json.dumps(detail, default=str) if not isinstance(detail, str) else detail),
        )


def read(ticket_id: str | None = None, limit: int = 500) -> list[dict]:
    con = _con()
    con.row_factory = sqlite3.Row
    if ticket_id:
        rows = con.execute("SELECT * FROM audit WHERE ticket_id=? ORDER BY id DESC LIMIT ?", (ticket_id, limit))
    else:
        rows = con.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]
