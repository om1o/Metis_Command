from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from fastapi.testclient import TestClient


ROOT = Path.cwd()


def _fresh_api_bridge():
    sys.modules.pop("api_bridge", None)
    sys.modules.pop("auth_local", None)
    import api_bridge
    return api_bridge


def _install_fake_browser(monkeypatch):
    fake = ModuleType("browser_runner")

    class FakePage:
        def __init__(self):
            self.url = "about:blank"
            self.last_fill = None
            self.last_click = None
            self.last_wait = None

        async def title(self):
            return "Fake Page"

    class FakeSession:
        async def open(self, *, headless=False):
            self.headless = headless

        async def new_page(self):
            return FakePage()

        async def close(self):
            return None

    async def navigate(page, url):
        page.url = url
        return {"url": url, "title": "Fake Page", "status": 200}

    async def screenshot_b64(_page):
        return "ZmFrZQ=="

    async def fill(page, selector, value, *, secret=False):
        page.last_fill = (selector, value, secret)

    async def click(page, selector):
        page.last_click = selector

    async def wait_for(page, selector, timeout_ms=10000):
        page.last_wait = (selector, timeout_ms)
        return {"selector": selector, "elapsed_ms": 12}

    fake.is_available = lambda: True
    fake.BrowserSession = FakeSession
    fake.navigate = navigate
    fake.screenshot_b64 = screenshot_b64
    fake.fill = fill
    fake.click = click
    fake.wait_for = wait_for
    fake.DAILY_ACCOUNT_CAP = 3
    fake.daily_account_count = lambda _date=None: 0
    fake._allowed_services = lambda: set()
    fake.create_account_assisted = lambda *args, **kwargs: {"ok": True}
    monkeypatch.setitem(sys.modules, "browser_runner", fake)

    policy = ModuleType("comms_policy")
    policy.is_allowed = lambda name: name == "chrome"
    monkeypatch.setitem(sys.modules, "comms_policy", policy)


def test_browser_mvp_safe_mode_queue_and_approval(_sandbox_paths, monkeypatch):
    _install_fake_browser(monkeypatch)
    api_bridge = _fresh_api_bridge()
    client = TestClient(api_bridge.app)
    headers = api_bridge.auth_local.bearer_header()

    status = client.get("/browser/status", headers=headers)
    assert status.status_code == 200
    body = status.json()
    assert body["mode"] == "safe"
    assert body["session_open"] is False

    assert client.post("/browser/click", headers=headers, json={"selector": "button"}).status_code == 409
    assert client.post("/browser/wait", headers=headers, json={"selector": ".ready"}).status_code == 409

    opened = client.post("/browser/open", headers=headers, json={"headless": True})
    assert opened.status_code == 200
    assert opened.json()["session_open"] is True

    navigated = client.post("/browser/navigate", headers=headers, json={"url": "https://github.com"})
    assert navigated.status_code == 200
    assert navigated.json()["url"] == "https://github.com"

    fill = client.post("/browser/fill", headers=headers, json={
        "selector": "input[name=email]",
        "value": "ops@metis.ai",
        "secret": False,
    })
    assert fill.status_code == 200
    assert fill.json()["queued"] is False

    queued = client.post("/browser/click", headers=headers, json={"selector": "button[type=submit]"})
    assert queued.status_code == 200
    assert queued.json()["queued"] is True
    approval_id = queued.json()["approval"]["id"]

    approvals = client.get("/browser/approvals", headers=headers)
    assert approvals.status_code == 200
    assert approvals.json()["approvals"][0]["id"] == approval_id

    approved = client.post(f"/browser/approvals/{approval_id}/approve", headers=headers)
    assert approved.status_code == 200
    assert approved.json()["approval"]["status"] == "approved"

    waited = client.post("/browser/wait", headers=headers, json={"selector": ".dashboard", "timeout_ms": 2500})
    assert waited.status_code == 200
    assert waited.json()["result"]["selector"] == ".dashboard"

    audit = client.get("/browser/audit?limit=20", headers=headers)
    assert audit.status_code == 200
    events = [row["event"] for row in audit.json()["events"]]
    assert "browser.approval_queued" in events
    assert "browser.approval_executed" in events


def test_browser_policy_blocks_configured_service(_sandbox_paths, monkeypatch):
    _install_fake_browser(monkeypatch)
    api_bridge = _fresh_api_bridge()
    client = TestClient(api_bridge.app)
    headers = api_bridge.auth_local.bearer_header()

    saved = client.post("/manager/config", headers=headers, json={
        "allowed_services": [
            {"domain": "example.com", "label": "Example", "enabled": False, "trusted": False, "daily_cap": 1}
        ]
    })
    assert saved.status_code == 200

    assert client.post("/browser/open", headers=headers, json={"headless": True}).status_code == 200
    blocked = client.post("/browser/navigate", headers=headers, json={"url": "https://example.com"})
    assert blocked.status_code == 403
    assert "blocks example.com" in blocked.json()["detail"]


def test_automation_events_and_run_now(_sandbox_paths, monkeypatch):
    _install_fake_browser(monkeypatch)
    daily_tasks = ModuleType("daily_tasks")
    daily_tasks.ACTIONS = {"demo_action": lambda: "ok"}
    monkeypatch.setitem(sys.modules, "daily_tasks", daily_tasks)

    api_bridge = _fresh_api_bridge()
    client = TestClient(api_bridge.app)
    headers = api_bridge.auth_local.bearer_header()

    created = client.post("/schedules", headers=headers, json={
        "goal": "Run a demo action",
        "kind": "interval",
        "spec": "60",
        "action": "demo_action",
        "name": "Demo action",
    })
    assert created.status_code == 200
    schedule_id = created.json()["id"]

    run = client.post(f"/schedules/{schedule_id}/run", headers=headers)
    assert run.status_code == 200
    body = run.json()
    assert body["ok"] is True
    assert body["event"]["status"] == "ok"
    assert body["event"]["trigger"] == "manual"

    events = client.get("/automation-events?limit=20", headers=headers)
    assert events.status_code == 200
    rows = events.json()["events"]
    assert rows
    assert rows[0]["schedule_id"] == schedule_id
    assert rows[0]["status"] == "ok"
