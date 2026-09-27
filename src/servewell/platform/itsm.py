"""Simulated ITSM tool endpoints (stand-in for ServiceNow/JSM) on SQLite."""

import json
import sqlite3
from datetime import datetime

from servewell.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    ticket_id TEXT PRIMARY KEY, store_id TEXT, subject TEXT, priority TEXT, category TEXT,
    status TEXT, routing TEXT, queue TEXT, confidence REAL, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id TEXT, author TEXT, visibility TEXT,
    body TEXT, created_at TEXT
);
"""


def _con() -> sqlite3.Connection:
    s = get_settings()
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(s.itsm_db)
    con.executescript(SCHEMA)
    return con


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def upsert_incident(ticket, status: str = "Open", routing: str | None = None,
                    queue: str | None = None, confidence: float | None = None) -> None:
    with _con() as con:
        con.execute(
            """INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(ticket_id) DO UPDATE SET status=excluded.status,
               routing=COALESCE(excluded.routing, routing), queue=COALESCE(excluded.queue, queue),
               confidence=COALESCE(excluded.confidence, confidence), updated_at=excluded.updated_at""",
            (ticket.ticket_id, ticket.store_id, ticket.subject, ticket.priority, ticket.category,
             status, routing, queue, confidence, _now()),
        )


def set_status(ticket_id: str, status: str) -> None:
    with _con() as con:
        con.execute("UPDATE incidents SET status=?, updated_at=? WHERE ticket_id=?",
                    (status, _now(), ticket_id))


def post_comment(ticket_id: str, body: str, author: str = "ServeWell Triage Agent",
                 visibility: str = "internal") -> None:
    with _con() as con:
        con.execute(
            "INSERT INTO comments (ticket_id, author, visibility, body, created_at) VALUES (?,?,?,?,?)",
            (ticket_id, author, visibility, body, _now()),
        )


def list_incidents() -> list[dict]:
    con = _con()
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute("SELECT * FROM incidents ORDER BY updated_at DESC")]


def list_comments(ticket_id: str | None = None) -> list[dict]:
    con = _con()
    con.row_factory = sqlite3.Row
    if ticket_id:
        rows = con.execute("SELECT * FROM comments WHERE ticket_id=? ORDER BY id", (ticket_id,))
    else:
        rows = con.execute("SELECT * FROM comments ORDER BY id DESC")
    return [dict(r) for r in rows]


def dumps(obj) -> str:
    return json.dumps(obj, default=str, indent=2)
