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

            -- FTS5 virtual table for full-text search over chat history.
            -- content=messages keeps the FTS index in sync via triggers below.
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                USING fts5(content, session_id UNINDEXED, role UNINDEXED,
                           content='messages', content_rowid='id');

            -- Keep FTS index in sync with the messages table.
            CREATE TRIGGER IF NOT EXISTS messages_ai
                AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, content, session_id, role)
                    VALUES (new.id, new.content, new.session_id, new.role);
                END;
            CREATE TRIGGER IF NOT EXISTS messages_ad
                AFTER DELETE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content, session_id, role)
                    VALUES ('delete', old.id, old.content, old.session_id, old.role);
                END;
            CREATE TRIGGER IF NOT EXISTS messages_au
                AFTER UPDATE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content, session_id, role)
                    VALUES ('delete', old.id, old.content, old.session_id, old.role);
                    INSERT INTO messages_fts(rowid, content, session_id, role)
                    VALUES (new.id, new.content, new.session_id, new.role);
                END;
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
        db = _get_local_db()
        rows = db.execute(
            "SELECT id, title, updated_at FROM sessions "
            "ORDER BY updated_at DESC",
        ).fetchall()
        return [dict(r) for r in rows]

    # Cloud fallback — just IDs, no titles.
    ids = list_sessions(user_id)
    return [{"id": sid, "title": "", "updated_at": ""} for sid in ids]


def rename_session(session_id: str, title: str, user_id: str | None = None) -> None:
    """Manually rename a session (pencil-icon in the sidebar)."""
    if _is_local(user_id):
        db = _get_local_db()
        db.execute(
            "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title.strip()[:120], _now_iso(), session_id),
        )
        db.commit()
        return
    # Cloud: no-op for now (Supabase has no title column).


def search_messages(
    query: str,
    user_id: str | None = None,
    limit: int = 20,
    session_id: str | None = None,
) -> list[dict]:
    """Full-text search over local chat history using SQLite FTS5.

    Returns matches with session title, snippet, role, and timestamp,
    newest first.  Each result includes a highlighted snippet of the
    matched content (FTS5 snippet() function, ~60 chars).

    Cloud users fall back to an empty list — Supabase full-text search
    is outside the local store's scope.
    """
    if not _is_local(user_id):
        return []

    query = query.strip()
    if not query:
        return []

    db = _get_local_db()

    # Rebuild FTS index if it looks empty (covers databases created before FTS
    # was introduced — triggers only fire for new writes, not old rows).
    fts_count = db.execute("SELECT COUNT(*) FROM messages_fts").fetchone()[0]
    msg_count = db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    if msg_count > 0 and fts_count == 0:
        db.execute("INSERT INTO messages_fts(messages_fts) VALUES ('rebuild')")
        db.commit()

    params: list[object] = [query]
    session_filter = ""
    if session_id:
        session_filter = "AND m.session_id = ?"
        params.append(session_id)
    params.append(limit)

    sql = f"""
        SELECT
            m.session_id,
            s.title        AS session_title,
            m.role,
            m.created_at,
            snippet(messages_fts, 0, '<b>', '</b>', '…', 15) AS snippet
        FROM messages_fts
        JOIN messages m  ON messages_fts.rowid = m.id
        JOIN sessions s  ON m.session_id = s.id
        WHERE messages_fts MATCH ?
        {session_filter}
        ORDER BY m.created_at DESC
        LIMIT ?
    """
    rows = db.execute(sql, params).fetchall()
    return [dict(r) for r in rows]
