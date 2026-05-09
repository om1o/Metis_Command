"""
Lightweight in-app notification feed.

A single JSON file at identity/inbox.json holds the most-recent items.
The HTTP layer (api_bridge.py) exposes CRUD; everywhere else uses
``append`` to drop a notification when something interesting happens
(job fired, relationship saved, daily briefing posted, etc.).

Schema per item:
    {
      "id":             str,                # 12-hex
      "title":          str,                # ≤ 160 chars
      "body":           str,                # ≤ 4000 chars
      "source":         str,                # "schedule:<id>" | "agent" | "manager:<role>"
      "created_at":     ISO 8601 string,
      "read":           bool,
      "schedule_id":    optional str,
      "relationship_id":optional str,
    }
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

INBOX_FILE = Path(__file__).parent / "identity" / "inbox.json"
_LOCK = threading.Lock()
_MAX_ITEMS = 200


def load() -> list[dict]:
    if not INBOX_FILE.exists():
        return []
    try:
        return json.loads(INBOX_FILE.read_text(encoding="utf-8")) or []
    except Exception:
        return []


def save(items: list[dict]) -> None:
    INBOX_FILE.parent.mkdir(parents=True, exist_ok=True)
    INBOX_FILE.write_text(
        json.dumps(items[:_MAX_ITEMS], indent=2),
        encoding="utf-8",
    )


def append(
    *,
    title: str,
    body: str = "",
    source: str = "agent",
    schedule_id: str | None = None,
    relationship_id: str | None = None,
) -> dict:
    item: dict = {
        "id": uuid.uuid4().hex[:12],
        "title": (title or "")[:160],
        "body": (body or "")[:4000],
        "source": source or "agent",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "read": False,
    }
    if schedule_id:
        item["schedule_id"] = schedule_id
    if relationship_id:
        item["relationship_id"] = relationship_id
    with _LOCK:
        items = load()
        items.insert(0, item)
        save(items)
    return item


def mark_read(iid: str) -> bool:
    with _LOCK:
        items = load()
        for it in items:
            if it.get("id") == iid:
                it["read"] = True
                save(items)
                return True
    return False


def remove(iid: str) -> bool:
    with _LOCK:
        items = load()
        before = len(items)
        items = [it for it in items if it.get("id") != iid]
        if len(items) == before:
            return False
        save(items)
    return True


def clear() -> int:
    with _LOCK:
        items = load()
        n = len(items)
        save([])
    return n
