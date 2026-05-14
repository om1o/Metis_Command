from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]


def test_auth_me_rejects_malformed_token_before_supabase(monkeypatch) -> None:
    import api_bridge

    called = False

    def fail_get_client():
        nonlocal called
        called = True
        raise AssertionError("Supabase should not be called for malformed tokens")

    monkeypatch.setitem(sys.modules, "supabase_client", SimpleNamespace(get_client=fail_get_client))
    client = TestClient(api_bridge.app)

    response = client.get(
        "/auth/me",
        headers={"Authorization": "Bearer sb_publishable_not_a_user_jwt"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "malformed or expired token"
    assert called is False


def test_protected_route_rejects_malformed_token_before_supabase(monkeypatch) -> None:
    import api_bridge

    called = False

    def fail_get_client():
        nonlocal called
        called = True
        raise AssertionError("Supabase should not be called for malformed tokens")

    monkeypatch.setitem(sys.modules, "supabase_client", SimpleNamespace(get_client=fail_get_client))
    client = TestClient(api_bridge.app)

    response = client.get(
        "/wallet",
        headers={"Authorization": "Bearer malformed.jwt"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert called is False


def test_html_shell_bootstraps_local_token_before_user_probe() -> None:
    api_js = (ROOT / "frontend" / "static" / "js" / "api.js").read_text(encoding="utf-8")

    assert "shouldReplaceStoredToken" in api_js
    assert "clearSession();" in api_js
    assert "bootstrapLocalSession();" in api_js
    assert "api.me()" in api_js
    assert api_js.index("bootstrapLocalSession();") < api_js.index("api.me()")


def test_next_desktop_bootstraps_local_install_token() -> None:
    page_tsx = (ROOT / "desktop-ui" / "src" / "app" / "page.tsx").read_text(encoding="utf-8")
    client_ts = (ROOT / "desktop-ui" / "src" / "lib" / "metis-client.ts").read_text(encoding="utf-8")

    assert "shouldReplaceStoredToken(saved, mode)" in page_tsx
    assert "getLocalToken()" in page_tsx
    assert "metis-auth-mode', 'local-install'" in page_tsx
    assert "async getLocalToken()" in client_ts
    assert "payload?.sub" in client_ts
