"""Navigation shell route and auth coverage."""

from __future__ import annotations

import sys
import re
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path.cwd()


def _fresh_api_bridge():
    """Reload route module after the test sandbox has replaced safety.PATHS."""
    sys.modules.pop("api_bridge", None)
    sys.modules.pop("auth_local", None)
    import api_bridge
    return api_bridge


def test_shell_pages_are_public_html(_sandbox_paths):
    api_bridge = _fresh_api_bridge()
    client = TestClient(api_bridge.app)
    for path, marker in (
        ("/app", "Metis"),
        ("/automations", "Automation"),
        ("/automation-inbox", "Automation"),
        ("/money", "Money"),
        ("/manager", "Manager"),
        ("/browser-control", "Browser"),
        ("/code", "Code"),
        ("/plugins", "Plugin"),
    ):
        response = client.get(path, headers={"accept": "text/html"})
        assert response.status_code == 200, path
        assert marker in response.text


def test_sidebar_nav_uses_requested_three_groups():
    nav = (ROOT / "frontend" / "static" / "js" / "nav.js").read_text(encoding="utf-8")
    groups = re.findall(r"\n  \{\n    id: '(chat|work|code)',", nav)
    assert groups == ["chat", "work", "code"]
    for label in ("New chat", "Recent chats", "Automation Inbox", "Generated files", "Plugin Store"):
        assert label in nav


def test_new_nav_does_not_expose_protected_json_without_token(_sandbox_paths):
    api_bridge = _fresh_api_bridge()
    client = TestClient(api_bridge.app)
    for path in ("/manager/config", "/marketplace", "/sessions", "/artifacts"):
        response = client.get(path)
        assert response.status_code == 401, path


def test_protected_json_still_accepts_local_token(_sandbox_paths):
    api_bridge = _fresh_api_bridge()
    client = TestClient(api_bridge.app)
    response = client.get(
        "/manager/config",
        headers=api_bridge.auth_local.bearer_header(),
    )
    assert response.status_code == 200
    body = response.json()
    assert "config" in body
    assert "specialists" in body


def test_code_workspace_api_stays_protected_and_token_works(_sandbox_paths, monkeypatch):
    monkeypatch.setenv("METIS_PROJECTS_ROOT", str(_sandbox_paths / "projects"))
    sys.modules.pop("code_workspace", None)
    api_bridge = _fresh_api_bridge()
    client = TestClient(api_bridge.app)

    assert client.get("/code/workspaces").status_code == 401
    response = client.get(
        "/code/workspaces",
        headers=api_bridge.auth_local.bearer_header(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["workspaces"] == []
    assert body["active"] is None
    assert body["root"].endswith("projects")
