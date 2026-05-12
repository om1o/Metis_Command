"""Conversation search and notification API contracts."""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient


def _fresh_memory():
    import memory

    return importlib.reload(memory)


def _fresh_notifications():
    import notifications

    return importlib.reload(notifications)


def test_search_messages_finds_local_chat_history(_sandbox_paths):
    memory = _fresh_memory()

    memory.save_message("s1", "user", "Find a business lawyer for a contract dispute.", user_id="local-install")
    memory.save_message("s1", "assistant", "I will gather local attorney options.", user_id="local-install")
    memory.save_message("s2", "user", "Check my stock portfolio.", user_id="local-install")

    results = memory.search_messages("lawyer", user_id="local-install")

    assert len(results) == 1
    assert results[0]["session_id"] == "s1"
    assert results[0]["role"] == "user"
    assert "<b>lawyer</b>" in results[0]["snippet"]


def test_search_messages_can_filter_by_session(_sandbox_paths):
    memory = _fresh_memory()

    memory.save_message("s1", "user", "Need a patent lawyer.", user_id="local-install")
    memory.save_message("s2", "user", "Need a real estate lawyer.", user_id="local-install")

    results = memory.search_messages("lawyer", user_id="local-install", session_id="s2")

    assert [row["session_id"] for row in results] == ["s2"]


def test_sessions_search_api_returns_matches(_sandbox_paths):
    import api_bridge

    memory = _fresh_memory()
    memory.save_message("api-session", "user", "Research a landlord lawyer.", user_id="local-install")

    client = TestClient(api_bridge.app)
    response = client.get(
        "/sessions/search",
        params={"q": "landlord", "limit": 5},
        headers=api_bridge.auth_local.bearer_header(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["session_id"] == "api-session"
    assert "<b>landlord</b>" in payload[0]["snippet"]


def test_youtube_search_api_returns_video_results(_sandbox_paths, monkeypatch):
    import api_bridge

    monkeypatch.setattr(
        api_bridge,
        "_youtube_search_results",
        lambda query, limit=5: [
            {
                "title": "AI Coding Agents for Real Apps",
                "url": "https://www.youtube.com/watch?v=abc123",
                "channel": "Builder Lab",
                "published": "1 week ago",
                "length": "12 minutes",
                "source": "youtube",
            }
        ],
    )

    client = TestClient(api_bridge.app)
    response = client.post(
        "/search/youtube",
        json={"query": "AI coding agents", "limit": 3},
        headers=api_bridge.auth_local.bearer_header(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "AI coding agents"
    assert payload["results"][0]["url"] == "https://www.youtube.com/watch?v=abc123"


def test_youtube_ai_coding_answer_uses_fast_search_path(_sandbox_paths, monkeypatch):
    import api_bridge

    monkeypatch.setattr(
        api_bridge,
        "_youtube_search_results",
        lambda query, limit=3: [
            {
                "title": "Claude Code vs Cursor for AI Coding",
                "url": "https://www.youtube.com/watch?v=def456",
                "channel": "AI Builders",
                "published": "2 days ago",
                "length": "18 minutes",
                "source": "youtube",
            }
        ],
    )

    answer = api_bridge._youtube_ai_coding_answer("Open YouTube and find a video on AI coding")

    assert answer is not None
    assert "Claude Code vs Cursor for AI Coding" in answer
    assert "https://www.youtube.com/watch?v=def456" in answer
    assert "YouTube search page:" in answer


def test_notifications_module_persists_metadata_and_marks_read(_sandbox_paths):
    notifications = _fresh_notifications()

    created = notifications.add(
        "Job finished",
        "The scheduled report is ready.",
        "success",
        metadata={"artifact_id": "art123", "schedule_id": "sched123"},
    )
    item = notifications.list_notifications()[0]

    assert notifications.unread_count() == 1
    assert item["id"] == created["id"]
    assert item["artifact_id"] == "art123"
    assert item["schedule_id"] == "sched123"
    assert item["metadata"] == {"artifact_id": "art123", "schedule_id": "sched123"}
    assert notifications.mark_read(created["id"]) is True
    assert notifications.unread_count() == 0
    assert notifications.clear() == 1
    assert notifications.list_notifications() == []


def test_notifications_api_lifecycle(_sandbox_paths):
    import api_bridge

    notifications = _fresh_notifications()
    notifications.clear()
    client = TestClient(api_bridge.app)

    created = client.post(
        "/notifications",
        json={
            "title": "Agent update",
            "body": "Manager finished the task.",
            "type": "agent",
            "metadata": {"artifact_id": "run456"},
        },
        headers=api_bridge.auth_local.bearer_header(),
    )
    assert created.status_code == 200
    notif_id = created.json()["id"]

    headers = api_bridge.auth_local.bearer_header()
    assert client.get("/notifications/count", headers=headers).json() == {"unread": 1}
    listed = client.get("/notifications", headers=headers).json()[0]
    assert listed["id"] == notif_id
    assert listed["artifact_id"] == "run456"
    assert client.post(f"/notifications/{notif_id}/read", headers=headers).json() == {"ok": True, "id": notif_id}
    assert client.get("/notifications/count", headers=headers).json() == {"unread": 0}
    assert client.delete("/notifications", headers=headers).json() == {"ok": True, "cleared": 1}


def test_analytics_accepts_iso_session_timestamps(_sandbox_paths, monkeypatch):
    import api_bridge
    import memory

    now = datetime.now(timezone.utc)

    def fake_sessions(_user_id: str):
        return [
            {"id": "recent-iso", "updated_at": now.isoformat()},
            {"id": "recent-ms", "updated_at": now.timestamp() * 1000},
            {"id": "old-iso", "updated_at": (now - timedelta(days=9)).isoformat()},
            {"id": "bad", "updated_at": "not-a-date"},
        ]

    monkeypatch.setattr(memory, "list_sessions_with_meta", fake_sessions)

    client = TestClient(api_bridge.app)
    response = client.get(
        "/analytics",
        headers=api_bridge.auth_local.bearer_header(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sessions"]["total"] == 4
    assert payload["sessions"]["active_last_7d"] == 2
