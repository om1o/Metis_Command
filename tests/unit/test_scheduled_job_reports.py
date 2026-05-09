"""Scheduled mission report artifacts."""

from __future__ import annotations

import time


class _DummyMission:
    status = "success"
    final_answer = "Scheduled job completed."


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

    reports = [
        artifact for artifact in list_artifacts()
        if artifact.metadata.get("kind") == "scheduled_job_report"
    ]
    assert len(reports) == 1
    report = reports[0]
    assert report.metadata["schedule_id"] == "market123"
    assert report.metadata["mission_id"] == record.id
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
