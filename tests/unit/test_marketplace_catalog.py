from __future__ import annotations

import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_builtin_catalog_is_default_and_does_not_touch_supabase(monkeypatch):
    monkeypatch.delenv("METIS_PLUGIN_CATALOG_SOURCE", raising=False)
    monkeypatch.delenv("METIS_PLUGIN_STORE_SOURCE", raising=False)

    def _fail_get_client():
        raise AssertionError("default plugin catalog must not query Supabase")

    monkeypatch.setitem(
        sys.modules,
        "supabase_client",
        SimpleNamespace(get_client=_fail_get_client),
    )

    sys.modules.pop("marketplace", None)
    from marketplace import list_plugins

    plugins = list_plugins()
    assert len(plugins) >= 5
    assert {plugin["slug"] for plugin in plugins} >= {
        "stock_terminal",
        "stealth_scraper",
        "discord_automator",
        "crypto_analyst",
        "spotify_controller",
    }


def test_supabase_catalog_source_falls_back_on_missing_table(monkeypatch):
    monkeypatch.setenv("METIS_PLUGIN_CATALOG_SOURCE", "supabase")

    class MissingTableQuery:
        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def order(self, *_args, **_kwargs):
            return self

        def execute(self):
            raise RuntimeError("404: relation public.plugins_store does not exist")

    class FakeClient:
        def table(self, name):
            assert name == "plugins_store"
            return MissingTableQuery()

    monkeypatch.setitem(
        sys.modules,
        "supabase_client",
        SimpleNamespace(get_client=lambda: FakeClient()),
    )

    sys.modules.pop("marketplace", None)
    from marketplace import list_plugins

    plugins = list_plugins()
    assert len(plugins) >= 5
    assert plugins[0]["slug"] == "stock_terminal"


def test_marketplace_api_returns_builtin_catalog_without_supabase_query(monkeypatch, _sandbox_paths):
    monkeypatch.delenv("METIS_PLUGIN_CATALOG_SOURCE", raising=False)
    monkeypatch.delenv("METIS_PLUGIN_STORE_SOURCE", raising=False)

    def _fail_get_client():
        raise AssertionError("/marketplace must not query Supabase by default")

    monkeypatch.setitem(
        sys.modules,
        "supabase_client",
        SimpleNamespace(get_client=_fail_get_client),
    )

    for module_name in ("api_bridge", "auth_local", "marketplace"):
        sys.modules.pop(module_name, None)
    import api_bridge

    client = TestClient(api_bridge.app)
    response = client.get(
        "/marketplace",
        headers=api_bridge.auth_local.bearer_header(),
    )

    assert response.status_code == 200
    plugins = response.json()
    assert len(plugins) >= 5
    assert all("installed" in plugin for plugin in plugins)
