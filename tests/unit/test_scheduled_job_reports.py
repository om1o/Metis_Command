"""Scheduled mission report artifacts."""

from __future__ import annotations

import time


class _DummyMission:
    status = "success"
    final_answer = "Scheduled job completed."


class _QueuedMission:
    id = "mission123"
    status = "queued"


class _ApiMission:
    def to_dict(self) -> dict:
        return {
            "id": "mission123",
            "status": "running",
            "tag": "scheduled:job123",
            "goal": "Run the market report now.",
        }


def test_scheduled_mission_saves_report_artifact(_sandbox_paths, monkeypatch):
    import autonomous_loop
    from artifacts import list_artifacts
    from concurrency import MissionPool
    import inbox

    def fake_run_mission(*, goal, on_event=None, **_kw):
        if on_event:
            on_event({"type": "mission_start", "goal": goal})
            on_event({"type": "finish", "answer": "Scheduled job completed."})
        return _DummyMission()

    monkeypatch.setattr(autonomous_loop, "run_mission", fake_run_mission)

    pool = MissionPool(max_workers=1, max_queue_depth=2)
    record = pool.submit("Check market summary.", tag="scheduled:market123", auto_approve=True)

    deadline = time.time() + 5
    while time.time() < deadline:
        current = pool.get(record.id)
        if current and current.status == "success":
            break
        time.sleep(0.05)

    current = pool.get(record.id)
    assert current is not None
    assert current.status == "success"

    reports = []
    deadline = time.time() + 5
    while time.time() < deadline:
        reports = [
            artifact for artifact in list_artifacts()
            if artifact.metadata.get("kind") == "scheduled_job_report"
        ]
        if reports:
            break
        time.sleep(0.05)
    assert len(reports) == 1
    report = reports[0]
    assert report.metadata["schedule_id"] == "market123"
    assert report.metadata["mission_id"] == record.id
    assert isinstance(report.created_at, float)
    assert report.metadata["created_at"] == report.created_at
    assert "Check market summary." in (report.content or "")
    assert "Scheduled job completed." in (report.content or "")

    items = []
    deadline = time.time() + 5
    while time.time() < deadline:
        items = inbox.load()
        if items:
            break
        time.sleep(0.05)
    assert items
    assert items[0]["artifact_id"] == report.id
    assert items[0]["schedule_id"] == "market123"


def test_run_now_uses_scheduled_report_tag(_sandbox_paths, monkeypatch):
    import scheduler

    seen: dict[str, str] = {}

    def fake_submit_mission(*, goal, tag, **_kw):
        seen["goal"] = goal
        seen["tag"] = tag
        return _QueuedMission()

    monkeypatch.setattr("concurrency.submit_mission", fake_submit_mission)

    sched = scheduler.add(
        "Run the market report now.",
        kind="daily",
        spec="09:00",
        mode="job",
        permission="balanced",
    )

    result = scheduler.run_now(sched.id)
    assert result is not None
    assert result["mission_id"] == "mission123"
    assert result["status"] == "queued"
    assert seen["tag"] == f"scheduled:{sched.id}"
    assert "Mode: Job" in seen["goal"]


def test_run_now_api_returns_mission_id(_sandbox_paths, monkeypatch):
    import api_bridge
    import scheduler
    from fastapi.testclient import TestClient

    def fake_submit_mission(**_kw):
        return _QueuedMission()

    monkeypatch.setattr("concurrency.submit_mission", fake_submit_mission)

    sched = scheduler.add(
        "Run the market report now.",
        kind="daily",
        spec="09:00",
        mode="job",
        permission="balanced",
    )

    client = TestClient(api_bridge.app)
    response = client.post(
        f"/schedules/{sched.id}/run",
        headers=api_bridge.auth_local.bearer_header(),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["id"] == sched.id
    assert data["mission_id"] == "mission123"
    assert data["status"] == "queued"


def test_mission_status_api_returns_record(_sandbox_paths, monkeypatch):
    import api_bridge
    from fastapi.testclient import TestClient

    monkeypatch.setattr("concurrency.get_mission", lambda mission_id: _ApiMission() if mission_id == "mission123" else None)

    client = TestClient(api_bridge.app)
    response = client.get(
        "/missions/mission123",
        headers=api_bridge.auth_local.bearer_header(),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "mission123"
    assert data["status"] == "running"
    assert data["tag"] == "scheduled:job123"


def test_missions_list_api_returns_records(_sandbox_paths, monkeypatch):
    import api_bridge
    from fastapi.testclient import TestClient

    monkeypatch.setattr("concurrency.list_missions", lambda limit=50: [_ApiMission()])
    monkeypatch.setattr("concurrency.load_persisted_history", lambda limit=100: [])

    client = TestClient(api_bridge.app)
    response = client.get(
        "/missions?limit=10",
        headers=api_bridge.auth_local.bearer_header(),
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "mission123"
    assert data[0]["status"] == "running"


def test_missions_list_api_includes_persisted_history(_sandbox_paths, monkeypatch):
    import api_bridge
    from fastapi.testclient import TestClient

    monkeypatch.setattr("concurrency.list_missions", lambda limit=50: [])
    monkeypatch.setattr("concurrency.load_persisted_history", lambda limit=100: [{
        "id": "persisted123",
        "status": "success",
        "tag": "scheduled:job123",
        "goal": "Persisted job run.",
        "submitted_at": 123.0,
    }])

    client = TestClient(api_bridge.app)
    response = client.get(
        "/missions?limit=10",
        headers=api_bridge.auth_local.bearer_header(),
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == "persisted123"
    assert data[0]["status"] == "success"


def test_mission_status_api_falls_back_to_persisted_history(_sandbox_paths, monkeypatch):
    import api_bridge
    from fastapi.testclient import TestClient

    monkeypatch.setattr("concurrency.get_mission", lambda mission_id: None)
    monkeypatch.setattr("concurrency.load_persisted_history", lambda limit=500: [{
        "id": "persisted123",
        "status": "success",
        "tag": "scheduled:job123",
        "goal": "Persisted job run.",
        "submitted_at": 123.0,
    }])

    client = TestClient(api_bridge.app)
    response = client.get(
        "/missions/persisted123",
        headers=api_bridge.auth_local.bearer_header(),
    )

    assert response.status_code == 200
    assert response.json()["id"] == "persisted123"


def test_mission_cancel_api_returns_result(_sandbox_paths, monkeypatch):
    import api_bridge
    from fastapi.testclient import TestClient

    seen: dict[str, str] = {}

    def fake_cancel_mission(mission_id: str) -> bool:
        seen["mission_id"] = mission_id
        return True

    monkeypatch.setattr("concurrency.cancel_mission", fake_cancel_mission)

    client = TestClient(api_bridge.app)
    response = client.post(
        "/missions/mission123/cancel",
        headers=api_bridge.auth_local.bearer_header(),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "id": "mission123"}
    assert seen["mission_id"] == "mission123"
