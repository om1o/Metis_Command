"""
Mission persistence store — survives Ctrl-C, crashes, and approval pauses.

Before this, autonomous_loop.run_mission lived entirely in memory. A
30-minute approval window meant the user had to keep the process alive
that whole time or lose every completed step. Now every step boundary
flushes Mission state to SQLite, and resume_mission(id) picks up where
the loop left off — already-done steps replayed from cache, in-flight
or pending steps re-executed.

Schema:

    CREATE TABLE missions (
        id           TEXT PRIMARY KEY,
        goal         TEXT NOT NULL,
        status       TEXT NOT NULL,        -- pending|running|paused|success|failed|stopped
        started_at   REAL NOT NULL,
        ended_at     REAL,
        user_id      TEXT,
        session_id   TEXT,
        final_answer TEXT,
        state_json   TEXT NOT NULL         -- full Mission as JSON (steps inline)
    );

The full Mission goes in state_json; the columns are just indexes for
listing / filtering. Updating one row per step is fine (~50 missions
total per user is high; 100MB SQLite handles 100k easily).
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import closing
from dataclasses import asdict, fields, is_dataclass
from pathlib import Path
from typing import Any, Iterable

DB_PATH = Path("identity") / "missions.db"


# ── Connection ──────────────────────────────────────────────────────────────

def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL;")
    c.execute("PRAGMA synchronous=NORMAL;")
    return c


def _init() -> None:
    with closing(_conn()) as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS missions (
                id           TEXT PRIMARY KEY,
                goal         TEXT NOT NULL,
                status       TEXT NOT NULL,
                started_at   REAL NOT NULL,
                ended_at     REAL,
                user_id      TEXT,
                session_id   TEXT,
                final_answer TEXT,
                state_json   TEXT NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS missions_status_idx ON missions(status)")
        c.execute("CREATE INDEX IF NOT EXISTS missions_started_idx ON missions(started_at)")
        c.commit()


_init()


# ── Serialization ───────────────────────────────────────────────────────────

def _to_dict(obj: Any) -> Any:
    """Recursively convert dataclasses → dicts, leaving everything else alone."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _to_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, list):
        return [_to_dict(x) for x in obj]
    if isinstance(obj, tuple):
        return [_to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


def _mission_to_json(mission: Any) -> str:
    return json.dumps(_to_dict(mission), default=str)


# ── Public API ──────────────────────────────────────────────────────────────

def new_id() -> str:
    """Generate a fresh mission id."""
    return uuid.uuid4().hex


def save(
    mission: Any,
    *,
    mission_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """Upsert mission state. Returns the mission id (creates one if absent)."""
    mid = mission_id or getattr(mission, "id", None) or new_id()
    # Stamp the id back onto the mission so callers don't lose it.
    if hasattr(mission, "id"):
        try:
            setattr(mission, "id", mid)
        except Exception:
            pass
    state_json = _mission_to_json(mission)
    with closing(_conn()) as c:
        c.execute("""
            INSERT INTO missions (id, goal, status, started_at, ended_at,
                                  user_id, session_id, final_answer, state_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                goal=excluded.goal,
                status=excluded.status,
                started_at=excluded.started_at,
                ended_at=excluded.ended_at,
                user_id=excluded.user_id,
                session_id=excluded.session_id,
                final_answer=excluded.final_answer,
                state_json=excluded.state_json
        """, (
            mid,
            getattr(mission, "goal", ""),
            getattr(mission, "status", "pending"),
            float(getattr(mission, "started_at", time.time())),
            getattr(mission, "ended_at", None),
            user_id, session_id,
            getattr(mission, "final_answer", "") or None,
            state_json,
        ))
        c.commit()
    return mid


def load_state(mission_id: str) -> dict[str, Any] | None:
    """Return the raw mission state dict (the JSON-decoded state_json),
    or None if no such mission. The autonomous loop rehydrates Mission
    + Step dataclasses from this — putting the rehydration in this
    module would tie us to autonomous_loop's import graph."""
    with closing(_conn()) as c:
        row = c.execute(
            "SELECT state_json FROM missions WHERE id = ?", (mission_id,)
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def get_meta(mission_id: str) -> dict[str, Any] | None:
    """Return just the indexed columns — fast list-page entry."""
    with closing(_conn()) as c:
        row = c.execute("""
            SELECT id, goal, status, started_at, ended_at, user_id,
                   session_id, final_answer
            FROM missions WHERE id = ?
        """, (mission_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row[0], "goal": row[1], "status": row[2],
        "started_at": row[3], "ended_at": row[4],
        "user_id": row[5], "session_id": row[6],
        "final_answer": row[7],
    }


def list_recent(
    *,
    user_id: str | None = None,
    statuses: Iterable[str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List missions newest-first. Filter by user and/or status set."""
    sql = "SELECT id, goal, status, started_at, ended_at, final_answer FROM missions"
    where: list[str] = []
    params: list[Any] = []
    if user_id:
        where.append("user_id = ?")
        params.append(user_id)
    if statuses:
        sset = list(statuses)
        where.append(f"status IN ({','.join('?' * len(sset))})")
        params.extend(sset)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY started_at DESC LIMIT ?"
    params.append(int(limit))
    with closing(_conn()) as c:
        rows = c.execute(sql, params).fetchall()
    return [
        {
            "id": r[0], "goal": r[1], "status": r[2],
            "started_at": r[3], "ended_at": r[4],
            "final_answer": r[5],
        }
        for r in rows
    ]


def delete(mission_id: str) -> bool:
    with closing(_conn()) as c:
        cur = c.execute("DELETE FROM missions WHERE id = ?", (mission_id,))
        c.commit()
        return cur.rowcount > 0


def mark_paused(mission_id: str) -> None:
    """Flip a mission to 'paused' without touching its steps. Useful
    when the autonomous loop hits a long approval wait and wants to
    surface a resumable state instead of blocking forever."""
    with closing(_conn()) as c:
        c.execute(
            "UPDATE missions SET status = 'paused' WHERE id = ?",
            (mission_id,),
        )
        c.commit()
