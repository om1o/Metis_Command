"""Local setup-code authentication contract."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_setup_code_round_trip(_sandbox_paths):
    import api_bridge

    client = TestClient(api_bridge.app)
    response = client.get("/auth/setup-code", headers={"host": "127.0.0.1:7331"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["type"] == "local-install"
    assert payload["code"].startswith(api_bridge.SETUP_CODE_PREFIX)

    token = api_bridge.setup_code_to_token(payload["code"])
    assert api_bridge.auth_local.verify(token)

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["id"] == "local-install"


def test_setup_code_normalization_accepts_copy_paste_noise(_sandbox_paths):
    import api_bridge
    import auth_local

    token = auth_local.get_or_create()
    messy = f"  '{api_bridge.SETUP_CODE_PREFIX}{token[:8]} \n {token[8:]}'  "

    assert api_bridge.setup_code_to_token(messy) == token
    assert api_bridge.setup_code_to_token(token) == token
    assert api_bridge.setup_code_to_token(None) == ""
