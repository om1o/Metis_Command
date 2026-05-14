"""Manager chat run reports."""

from __future__ import annotations

import json
import importlib

from fastapi.testclient import TestClient


def _events(response_text: str) -> list[dict]:
    out: list[dict] = []
    for line in response_text.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


def test_chat_saves_manager_run_artifact(_sandbox_paths, monkeypatch):
    import api_bridge
    import manager_orchestrator
    from artifacts import get_artifact

    def fake_orchestrate(_message: str, *, user_id: str, session_id: str, **_kwargs):
        assert user_id == "local-install"
        assert session_id == "artifact-smoke"
        yield {
            "type": "manager_plan",
            "summary": "Use researcher then answer.",
            "agents": ["researcher"],
            "self_handle": False,
        }
        yield {
            "type": "agent_done",
            "agent": "researcher",
            "output": "Found source data.",
            "duration_ms": 25,
        }
        yield {"type": "token", "delta": "Final answer."}
        yield {"type": "done", "duration_ms": 50, "agents_used": ["researcher"]}

    monkeypatch.setattr(manager_orchestrator, "orchestrate", fake_orchestrate)

    client = TestClient(api_bridge.app)
    response = client.post(
        "/chat",
        headers=api_bridge.auth_local.bearer_header(),
        json={
            "session_id": "artifact-smoke",
            "message": "Find me a lawyer.",
            "role": "manager",
            "mode": "task",
            "permission": "read",
        },
    )

    assert response.status_code == 200
    events = _events(response.text)
    saved = [event for event in events if event.get("type") == "run_artifact_saved"]
    assert len(saved) == 1
    assert events.index(saved[0]) < next(i for i, event in enumerate(events) if event.get("type") == "done")

    artifact = get_artifact(saved[0]["id"])
    assert artifact is not None
    assert artifact.metadata["kind"] == "manager_run_report"
    assert artifact.metadata["mode"] == "task"
    assert artifact.metadata["permission"] == "read"
    assert isinstance(artifact.created_at, float)
    assert artifact.metadata["created_at"] == artifact.created_at
    assert "Find me a lawyer." in artifact.content
    assert "Use researcher then answer." in artifact.content
    assert "Found source data." in artifact.content
    assert "Final answer." in artifact.content


def test_chat_relationship_save_creates_desktop_notification(_sandbox_paths, monkeypatch):
    import api_bridge
    import manager_orchestrator
    import notifications

    notifications = importlib.reload(notifications)

    def fake_orchestrate(_message: str, *, user_id: str, session_id: str, **_kwargs):
        assert user_id == "local-install"
        assert session_id == "relationship-notify"
        yield {
            "type": "token",
            "delta": (
                "I found the right contact.\n\n"
                "```relationship\n"
                + json.dumps({
                    "name": "Taylor Legal",
                    "role": "Attorney",
                    "company": "Taylor Legal PLLC",
                    "email": "hello@example.test",
                    "notes": "Business contract consultation.",
                    "tags": ["lawyer"],
                })
                + "\n```"
            ),
        }
        yield {"type": "done", "duration_ms": 40, "agents_used": []}

    monkeypatch.setattr(manager_orchestrator, "orchestrate", fake_orchestrate)

    client = TestClient(api_bridge.app)
    response = client.post(
        "/chat",
        headers=api_bridge.auth_local.bearer_header(),
        json={
            "session_id": "relationship-notify",
            "message": "Find me a lawyer.",
            "role": "manager",
            "mode": "task",
            "permission": "read",
        },
    )

    assert response.status_code == 200
    events = _events(response.text)
    saved_events = [event for event in events if event.get("type") == "relationship_saved"]
    assert len(saved_events) == 1
    assert saved_events[0]["name"] == "Taylor Legal"

    alerts = notifications.list_notifications()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["type"] == "agent"
    assert alert["title"] == "Saved Taylor Legal"
    assert "Business contract consultation." in alert["body"]
    assert alert["source"] == "manager:relationship"
    assert alert["relationship_id"] == saved_events[0]["id"]
    assert alert["metadata"] == {
        "source": "manager:relationship",
        "relationship_id": saved_events[0]["id"],
    }


def test_artifact_delete_api_removes_report(_sandbox_paths):
    import api_bridge
    from artifacts import Artifact, get_artifact, save_artifact

    artifact = save_artifact(Artifact(
        type="doc",
        title="Disposable report",
        content="remove me",
        metadata={"kind": "manager_run_report"},
    ))

    client = TestClient(api_bridge.app)
    response = client.delete(
        f"/artifacts/{artifact.id}",
        headers=api_bridge.auth_local.bearer_header(),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "id": artifact.id}
    assert get_artifact(artifact.id) is None
