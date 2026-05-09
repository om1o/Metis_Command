from __future__ import annotations

import sys
import types


def test_export_import_skips_vector_memory_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("METIS_CHAT_VECTOR_MEMORY", raising=False)

    exploding_module = types.ModuleType("memory_vault")

    class ExplodingBank:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("MTS default path should not initialize vector memory")

    exploding_module.MemoryBank = ExplodingBank
    monkeypatch.setitem(sys.modules, "memory_vault", exploding_module)

    from mts_format import export_identity, import_identity

    path = tmp_path / "identity.mts"
    export_identity(str(path), password="smoke")
    payload = import_identity(str(path), password="smoke")

    assert payload["kind"] == "MetisThoughtState"
    assert payload["identity_facts"] == []


def test_export_import_uses_vector_memory_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("METIS_CHAT_VECTOR_MEMORY", "1")
    stores: list[str] = []

    fake_module = types.ModuleType("memory_vault")

    class FakeBank:
        def search(self, *_args, **_kwargs):
            return [{"document": "Director prefers concise status updates."}]

        def store_interaction(self, *, facts: str, **_kwargs):
            stores.append(facts)

    fake_module.MemoryBank = FakeBank
    monkeypatch.setitem(sys.modules, "memory_vault", fake_module)

    from mts_format import export_identity, import_identity

    path = tmp_path / "identity.mts"
    export_identity(str(path))
    payload = import_identity(str(path))

    assert payload["identity_facts"] == ["Director prefers concise status updates."]
    assert stores == ["Director prefers concise status updates."]
