"""
Ruflo Memory plugin for Metis Command.

Exposes persistent memory (store/search) backed by Ruflo's SQLite database
at ~/ruflo-agent/ruvector.db.  Uses only stdlib — no external deps.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DESCRIPTION = (
    "Ruflo Memory — store observations and search across them using a local "
    "SQLite database (~/.ruflo-agent/ruvector.db).  Use store() to save "
    "findings and search() to recall them later."
)

_DB_PATH = Path.home() / "ruflo-agent" / "ruvector.db"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS observations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT,
    content    TEXT,
    tags       TEXT,
    created_at TEXT
)
"""


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute(_CREATE_SQL)
    con.commit()
    return con


def search(query: str, limit: int = 5) -> list[dict]:
    """
    Return up to `limit` observations whose title, content, or tags contain
    `query` (case-insensitive LIKE match).
    """
    pattern = f"%{query}%"
    with _connect() as con:
        rows = con.execute(
            """
            SELECT id, title, content, tags, created_at
            FROM observations
            WHERE title    LIKE ? COLLATE NOCASE
               OR content  LIKE ? COLLATE NOCASE
               OR tags     LIKE ? COLLATE NOCASE
            ORDER BY id DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def store(title: str, content: str, tags: str = "") -> bool:
    """
    Insert a new observation row.  Returns True on success, False on error.
    """
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        with _connect() as con:
            con.execute(
                "INSERT INTO observations (title, content, tags, created_at) VALUES (?, ?, ?, ?)",
                (title, content, tags, created_at),
            )
            con.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[ruflo] store() failed: {exc}")
        return False
