"""
Notification system for Metis — agents and scheduled jobs can post
in-app alerts that the UI picks up via GET /notifications.

Design:
- In-memory ring buffer (deque, max 200 entries) — zero-config, fast.
- Persisted to SQLite alongside chat memory so notifications survive
  restarts (optional: enabled by default for the local-install path).
- Thread-safe via a module-level lock.

Notification types
------------------
  info     — generic informational message
  success  — task / mission completed
  warning  — something needs the user's attention
  error    — something failed
  agent    — a persistent agent has something to say
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


NotificationType = Literal["info", "success", "warning", "error", "agent"]

_MAX_QUEUE = 200
_SQLITE_PATH = Path("identity") / "local_chat.db"

_lock = threading.Lock()
_queue: deque[dict] = deque(maxlen=_MAX_QUEUE)
_db_conn: sqlite3.Connection | None = None
_db_ready = False


# ── SQLite persistence ────────────────────────────────────────────────────────

def _get_db() -> sqlite3.Connection | None:
    global _db_conn, _db_ready
    if _db_ready:
        return _db_conn
    try:
        _SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_SQLITE_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notifications (
                id         TEXT PRIMARY KEY,
                type       TEXT NOT NULL DEFAULT 'info',
                title      TEXT NOT NULL,
                body       TEXT NOT NULL DEFAULT '',
                read       INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notif_created
                ON notifications(created_at DESC);
        """)
        conn.commit()
        _db_conn = conn
        _db_ready = True
        return conn
    except Exception:
        _db_ready = True  # mark done even on failure so we don't retry every call
        return None


def _persist(notif: dict) -> None:
    conn = _get_db()
    if conn is None:
        return
    try:
        conn.execute(
            "INSERT OR IGNORE INTO notifications (id, type, title, body, read, created_at) "
            "VALUES (:id, :type, :title, :body, :read, :created_at)",
            {
                "id": notif["id"],
                "type": notif["type"],
                "title": notif["title"],
                "body": notif.get("body", ""),
                "read": 1 if notif.get("read") else 0,
                "created_at": notif["created_at"],
            },
        )
        conn.commit()
    except Exception:
        pass


def _load_from_db(limit: int = _MAX_QUEUE) -> list[dict]:
    conn = _get_db()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT id, type, title, body, read, created_at FROM notifications "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _mark_read_db(notif_id: str) -> None:
    conn = _get_db()
    if conn is None:
        return
    try:
        conn.execute("UPDATE notifications SET read = 1 WHERE id = ?", (notif_id,))
        conn.commit()
    except Exception:
        pass


def _clear_db() -> None:
    conn = _get_db()
    if conn is None:
        return
    try:
        conn.execute("DELETE FROM notifications")
        conn.commit()
    except Exception:
        pass


# ── Bootstrap: hydrate in-memory queue from DB on first use ──────────────────

_hydrated = False


def _ensure_hydrated() -> None:
    global _hydrated
    if _hydrated:
        return
    _hydrated = True
    for row in _load_from_db():
        _queue.appendleft(row)


# ── Public API ────────────────────────────────────────────────────────────────

def add(
    title: str,
    body: str = "",
    notif_type: NotificationType = "info",
) -> dict:
    """Create a new notification and return it.

    Thread-safe.  The notification is added to both the in-memory ring
    buffer and the SQLite persistence store.
    """
    notif: dict = {
        "id": str(uuid.uuid4()),
        "type": notif_type,
        "title": title.strip()[:200],
        "body": body.strip()[:2000],
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with _lock:
        _ensure_hydrated()
        _queue.appendleft(notif)
    _persist(notif)
    return notif


def list_notifications(
    limit: int = 50,
    unread_only: bool = False,
) -> list[dict]:
    """Return recent notifications, newest first."""
    with _lock:
        _ensure_hydrated()
        items = list(_queue)

    if unread_only:
        items = [n for n in items if not n.get("read")]
    return items[:limit]


def mark_read(notif_id: str) -> bool:
    """Mark a single notification as read.  Returns True if found."""
    with _lock:
        _ensure_hydrated()
        for notif in _queue:
            if notif["id"] == notif_id:
                notif["read"] = True
                _mark_read_db(notif_id)
                return True
    return False


def mark_all_read() -> int:
    """Mark every notification as read.  Returns the count marked."""
    count = 0
    with _lock:
        _ensure_hydrated()
        for notif in _queue:
            if not notif.get("read"):
                notif["read"] = True
                _mark_read_db(notif["id"])
                count += 1
    return count


def clear() -> int:
    """Delete all notifications.  Returns the count removed."""
    with _lock:
        _ensure_hydrated()
        count = len(_queue)
        _queue.clear()
    _clear_db()
    return count


def unread_count() -> int:
    with _lock:
        _ensure_hydrated()
        return sum(1 for n in _queue if not n.get("read"))
