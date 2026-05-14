from __future__ import annotations

from fastapi.testclient import TestClient


def _client():
    import api_bridge
    return TestClient(api_bridge.app), api_bridge.auth_local.bearer_header()


def test_browser_status_endpoint_reports_not_running(_sandbox_paths, monkeypatch):
    import tools.browser_agent as ba

    monkeypatch.setattr(ba.browser, "_page", None, raising=False)
    client, headers = _client()

    response = client.get("/browser/status", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "running": False}


def test_browser_navigation_blocks_disabled_service(_sandbox_paths):
    import manager_config

    manager_config.save_config("local-install", {"allowed_services": {"example.com": False}})
    client, headers = _client()

    response = client.post(
        "/browser/navigate",
        headers=headers,
        json={"url": "https://example.com", "headless": True},
    )

    assert response.status_code == 403
    assert "disabled" in response.json()["detail"]


def test_browser_approvals_list_and_approve(_sandbox_paths):
    import permissions

    # Seed a pending approval directly; request_approval intentionally blocks
    # until the operator decides, which would make this API test slow.
    permissions._PENDING["abc123"] = {"tool": "browser.goto", "summary": "browser", "args": {}, "ts": 1.0}
    permissions._DECISION_EVENTS["abc123"] = __import__("threading").Event()

    client, headers = _client()
    response = client.get("/browser/approvals", headers=headers)
    assert response.status_code == 200
    assert response.json()["approvals"][0]["id"] == "abc123"

    approve = client.post("/browser/approvals/abc123/approve", headers=headers)
    assert approve.status_code == 200
    assert approve.json()["decision"] == "approve"


def test_run_now_persists_automation_event(_sandbox_paths, monkeypatch):
    import scheduler

    class Mission:
        id = "mission123"
        status = "queued"

    monkeypatch.setattr("concurrency.submit_mission", lambda **_kw: Mission())
    sched = scheduler.add("Run a manual automation.", kind="daily", spec="09:00")

    result = scheduler.run_now(sched.id)
    events = scheduler.list_events()

    assert result is not None
    assert result["event"]["schedule_id"] == sched.id
    assert events[0]["schedule_id"] == sched.id
    assert events[0]["trigger"] == "manual"


def test_automation_events_endpoint_returns_history(_sandbox_paths, monkeypatch):
    import scheduler

    sched = scheduler.add("Manual history.", kind="daily", spec="09:00")
    scheduler.append_event(sched, trigger="manual", status="queued", details={"mission_id": "m1"})

    client, headers = _client()
    response = client.get("/automation-events", headers=headers)

    assert response.status_code == 200
    events = response.json()["events"]
    assert events[0]["schedule_id"] == sched.id
    assert events[0]["details"]["mission_id"] == "m1"
