"""Manager chat run reports."""

from __future__ import annotations

import json

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

    def fake_orchestrate(_message: str, *, user_id: str, session_id: str):
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
