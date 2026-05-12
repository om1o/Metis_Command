"""
Memory module — persists Metis conversation history.

Two backends:
  1. SQLite  (local-install / default users) — zero-config, stored at
     ``identity/local_chat.db``.  This is the primary path for desktop users.
  2. Supabase (cloud users with a real JWT) — original behaviour, requires
     the ``memory`` table created by schema.sql.

The public API (``save_message``, ``load_session``, ``clear_session``,
``list_sessions``, ``list_sessions_with_meta``) auto-routes based on
``user_id``.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ── SQLite local store ──────────────────────────────────────────────────────

_SQLITE_PATH = Path("identity") / "local_chat.db"
_local_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


def _get_local_db() -> sqlite3.Connection:
    """Lazy-init the local SQLite database (thread-safe singleton)."""
    global _local_conn
    if _local_conn is not None:
        return _local_conn
    with _lock:
        if _local_conn is not None:          # double-check after lock
            return _local_conn
        _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_SQLITE_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role       TEXT NOT NULL,
                content    TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session
                ON messages(session_id);
            CREATE TABLE IF NOT EXISTS jobs (
                id         TEXT PRIMARY KEY,
                title      TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                schedule   TEXT NOT NULL DEFAULT '',
                status     TEXT NOT NULL DEFAULT 'pending',
                agent_team TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        conn.commit()
        _local_conn = conn
        return conn


def _is_local(user_id: str | None) -> bool:
    """True when the caller is a desktop / local-install user."""
    return user_id in (None, "", "local-install", "default")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_session(db: sqlite3.Connection, session_id: str) -> None:
    """Create the session row if it doesn't exist yet (title stays blank)."""
    now = _now_iso()
    db.execute(
        "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at) "
        "VALUES (?, '', ?, ?)",
        (session_id, now, now),
    )


def _auto_title(content: str) -> str:
    """Derive a short title from the first user message."""
    title = content.strip().replace("\n", " ")[:60]
    if len(content.strip()) > 60:
        # try to break at a word boundary
        sp = title.rsplit(" ", 1)
        title = sp[0] + "…" if len(sp) > 1 else title + "…"
    return title


# ── Public API ──────────────────────────────────────────────────────────────

def save_message(
    session_id: str,
    role: str,
    content: str,
    user_id: str | None = None,
) -> dict:
    """Append a message to the memory store and return the inserted row."""

    if _is_local(user_id):
        with _lock:
            db = _get_local_db()
            now = _now_iso()
            _ensure_session(db, session_id)

            # First user message in this session becomes the title.
            if role == "user":
                row = db.execute(
                    "SELECT COUNT(*) AS c FROM messages "
                    "WHERE session_id = ? AND role = 'user'",
                    (session_id,),
                ).fetchone()
                if row["c"] == 0:
                    db.execute(
                        "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                        (_auto_title(content), now, session_id),
                    )

            db.execute(
                "INSERT INTO messages (session_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (session_id, role, content, now),
            )
            db.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (now, session_id),
            )
            db.commit()
        return {
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": now,
        }

    # ── Cloud path: Supabase ────────────────────────────────────────────
    from supabase_client import get_client

    client = get_client()
    payload = {"session_id": session_id, "role": role, "content": content}
    if user_id:
        payload["user_id"] = user_id
    response = client.table("memory").insert(payload).execute()
    return response.data[0] if response.data else {}


def load_session(
    session_id: str,
    limit: int = 50,
    user_id: str | None = None,
) -> list[dict]:
    """Retrieve the last ``limit`` messages for a session, oldest-first."""

    if _is_local(user_id):
        with _lock:
            db = _get_local_db()
            rows = db.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    from supabase_client import get_client

    client = get_client()
    response = (
        client.table("memory")
        .select("role, content, created_at")
        .eq("session_id", session_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return response.data or []


def clear_session(session_id: str, user_id: str | None = None) -> None:
    """Delete all memory rows (and the session record) for a given session."""

    if _is_local(user_id):
        with _lock:
            db = _get_local_db()
            db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            db.commit()
        return

    from supabase_client import get_client

    client = get_client()
    client.table("memory").delete().eq("session_id", session_id).execute()


def list_sessions(user_id: str) -> list[str]:
    """Return distinct session IDs belonging to a user (most-recent first)."""

    if _is_local(user_id):
        with _lock:
            db = _get_local_db()
            rows = db.execute(
                "SELECT id FROM sessions ORDER BY updated_at DESC",
            ).fetchall()
        return [r["id"] for r in rows]

    from supabase_client import get_client

    client = get_client()
    response = (
        client.table("memory")
        .select("session_id")
        .eq("user_id", user_id)
        .execute()
    )
    seen: set[str] = set()
    sessions: list[str] = []
    for row in response.data or []:
        sid = row["session_id"]
        if sid not in seen:
            seen.add(sid)
            sessions.append(sid)
    return sessions


def list_sessions_with_meta(user_id: str) -> list[dict]:
    """Return sessions with ``id``, ``title``, ``updated_at`` for the sidebar.

    Local users get full metadata from SQLite.  Cloud users get bare IDs
    (Supabase ``memory`` table has no title column).
    """
    if _is_local(user_id):
        with _lock:
            db = _get_local_db()
            rows = db.execute(
                "SELECT id, title, updated_at FROM sessions "
                "ORDER BY updated_at DESC",
            ).fetchall()
        return [dict(r) for r in rows]

    # Cloud fallback — just IDs, no titles.
    ids = list_sessions(user_id)
    return [{"id": sid, "title": "", "updated_at": ""} for sid in ids]


def search_messages(
    query: str,
    user_id: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search message content across all sessions.

    Returns a deduplicated list of ``{session_id, title, snippet, created_at,
    role}`` dicts — one entry per session, showing the best matching snippet.
    """
    if not query or not query.strip():
        return []
    if not _is_local(user_id):
        return []  # Cloud path: no-op for now

    with _lock:
        db = _get_local_db()
        q_like = f"%{query.strip()}%"
        rows = db.execute(
            """
            SELECT m.session_id, s.title, m.content, m.created_at, m.role
            FROM   messages m
            JOIN   sessions s ON s.id = m.session_id
            WHERE  m.content LIKE ? ESCAPE '\\'
            ORDER  BY m.created_at DESC
            LIMIT  ?
            """,
            (q_like, limit * 3),   # over-fetch so dedup yields `limit` unique sessions
        ).fetchall()

    seen: set[str] = set()
    results: list[dict] = []
    q_lower = query.strip().lower()
    for row in rows:
        sid = row["session_id"]
        if sid in seen:
            continue
        seen.add(sid)
        content: str = row["content"] or ""
        idx = content.lower().find(q_lower)
        if idx >= 0:
            start = max(0, idx - 60)
            end = min(len(content), idx + len(query) + 60)
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(content) else ""
            snippet = prefix + content[start:end].strip() + suffix
        else:
            snippet = content[:120].strip() + ("…" if len(content) > 120 else "")
        results.append({
            "session_id": sid,
            "title":      row["title"] or sid,
            "snippet":    snippet,
            "created_at": row["created_at"],
            "role":       row["role"],
        })
        if len(results) >= limit:
            break
    return results


def message_count(session_id: str, user_id: str | None = None) -> int:
    """Return the total number of messages stored for a session."""
    if _is_local(user_id):
        with _lock:
            db = _get_local_db()
            row = db.execute(
                "SELECT COUNT(*) AS c FROM messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["c"])
    return 0


def rename_session(session_id: str, title: str, user_id: str | None = None) -> None:
    """Manually rename a session (pencil-icon in the sidebar)."""
    if _is_local(user_id):
        with _lock:
            db = _get_local_db()
            db.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title.strip()[:120], _now_iso(), session_id),
            )
            db.commit()
        return
    # Cloud: no-op for now (Supabase has no title column).


def create_job(title: str, description: str = "", schedule: str = "", agent_team: list | None = None) -> dict:
    """Create a new job and return its dict."""
    import json
    with _lock:
        db = _get_local_db()
        now = _now_iso()
        job_id = uuid.uuid4().hex[:12]
        team_json = json.dumps(agent_team or [])
        db.execute(
            "INSERT INTO jobs (id, title, description, schedule, status, agent_team, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
            (job_id, title.strip()[:120], description, schedule, team_json, now, now),
        )
        db.commit()
    return {"id": job_id, "title": title.strip()[:120], "description": description, "schedule": schedule, "status": "pending", "agent_team": agent_team or [], "created_at": now}


def list_jobs(status: str | None = None) -> list[dict]:
    """Return all jobs, optionally filtered by status."""
    import json
    with _lock:
        db = _get_local_db()
        if status:
            rows = db.execute("SELECT * FROM jobs WHERE status = ? ORDER BY updated_at DESC", (status,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
    results = []
    for r in rows:
        d = dict(r)
        try:
            d["agent_team"] = json.loads(d.get("agent_team", "[]"))
        except Exception:
            d["agent_team"] = []
        results.append(d)
    return results


def update_job_status(job_id: str, status: str) -> None:
    """Update a job's status."""
    with _lock:
        db = _get_local_db()
        db.execute("UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?", (status, _now_iso(), job_id))
        db.commit()


def delete_job(job_id: str) -> None:
    """Delete a job by id."""
    with _lock:
        db = _get_local_db()
        db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        db.commit()
