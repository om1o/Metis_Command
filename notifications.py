"""Persistent in-app notifications for Metis.

Agents, scheduled jobs, and API clients can post alerts that the desktop UI can
poll through the notifications API routes. Notifications are kept in a small
in-memory queue and persisted to the local identity SQLite database.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from safety import PATHS


NotificationType = Literal["info", "success", "warning", "error", "agent"]

_MAX_QUEUE = 200
_lock = threading.Lock()
_queue: deque[dict] = deque(maxlen=_MAX_QUEUE)
_db_conn: sqlite3.Connection | None = None
_db_ready = False
_hydrated = False


def _sqlite_path() -> Path:
    return Path(PATHS.identity) / "local_chat.db"


def _get_db() -> sqlite3.Connection | None:
    global _db_conn, _db_ready
    if _db_ready:
        return _db_conn
    try:
        sqlite_path = _sqlite_path()
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(sqlite_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notifications (
                id         TEXT PRIMARY KEY,
                type       TEXT NOT NULL DEFAULT 'info',
                title      TEXT NOT NULL,
                body       TEXT NOT NULL DEFAULT '',
                read       INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                metadata   TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_created
                ON notifications(created_at DESC);
        """)
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(notifications)").fetchall()}
        if "metadata" not in cols:
            conn.execute("ALTER TABLE notifications ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
        conn.commit()
        _db_conn = conn
        _db_ready = True
        return conn
    except Exception:
        _db_ready = True
        return None


def _persist(notif: dict) -> None:
    conn = _get_db()
    if conn is None:
        return
    try:
        conn.execute(
            "INSERT OR IGNORE INTO notifications (id, type, title, body, read, created_at, metadata) "
            "VALUES (:id, :type, :title, :body, :read, :created_at, :metadata)",
            {
                "id": notif["id"],
                "type": notif["type"],
                "title": notif["title"],
                "body": notif.get("body", ""),
                "read": 1 if notif.get("read") else 0,
                "created_at": notif["created_at"],
                "metadata": json.dumps(notif.get("metadata") or {}),
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
            "SELECT id, type, title, body, read, created_at, metadata FROM notifications "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        items = []
        for row in rows:
            item = {**dict(row), "read": bool(row["read"])}
            try:
                metadata = json.loads(str(item.pop("metadata") or "{}"))
            except Exception:
                metadata = {}
            if isinstance(metadata, dict):
                item["metadata"] = metadata
                item.update(metadata)
            else:
                item["metadata"] = {}
            items.append(item)
        return items
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


def _ensure_hydrated() -> None:
    global _hydrated
    if _hydrated:
        return
    _hydrated = True
    for row in reversed(_load_from_db()):
        _queue.appendleft(row)


def add(
    title: str,
    body: str = "",
    notif_type: NotificationType = "info",
    metadata: dict | None = None,
) -> dict:
    """Create and persist a notification."""
    clean_metadata = dict(metadata or {})
    notif: dict = {
        "id": str(uuid.uuid4()),
        "type": notif_type,
        "title": title.strip()[:200],
        "body": body.strip()[:2000],
        "read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": clean_metadata,
        **clean_metadata,
    }
    with _lock:
        _ensure_hydrated()
        _queue.appendleft(notif)
    _persist(notif)
    return notif


def list_notifications(limit: int = 50, unread_only: bool = False) -> list[dict]:
    """Return recent notifications, newest first."""
    with _lock:
        _ensure_hydrated()
        items = list(_queue)
    if unread_only:
        items = [item for item in items if not item.get("read")]
    return items[:limit]


def mark_read(notif_id: str) -> bool:
    """Mark a single notification as read."""
    with _lock:
        _ensure_hydrated()
        for notif in _queue:
            if notif["id"] == notif_id:
                notif["read"] = True
                _mark_read_db(notif_id)
                return True
    return False


def mark_all_read() -> int:
    """Mark every unread notification as read."""
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
    """Delete all notifications."""
    with _lock:
        _ensure_hydrated()
        count = len(_queue)
        _queue.clear()
    _clear_db()
    return count


def unread_count() -> int:
    with _lock:
        _ensure_hydrated()
        return sum(1 for notif in _queue if not notif.get("read"))
