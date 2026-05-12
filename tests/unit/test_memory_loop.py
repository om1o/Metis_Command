from __future__ import annotations

import importlib


class ExplodingBank:
    def search(self, *_args, **_kwargs):
        raise AssertionError("vector memory should be disabled by default")

    def store_interaction(self, *_args, **_kwargs):
        raise AssertionError("vector memory should be disabled by default")


class RecordingBank:
    def __init__(self):
        self.searches = []
        self.stores = []

    def search(self, *args, **kwargs):
        self.searches.append((args, kwargs))
        return [{"document": "Director prefers concise status updates."}]

    def store_interaction(self, *args, **kwargs):
        self.stores.append((args, kwargs))


def _fresh_memory_loop(monkeypatch):
    monkeypatch.delenv("METIS_CHAT_VECTOR_MEMORY", raising=False)
    import memory
    import memory_loop

    memory._local_conn = None
    return importlib.reload(memory_loop)


def test_persist_turn_skips_vector_memory_by_default(monkeypatch):
    memory_loop = _fresh_memory_loop(monkeypatch)
    monkeypatch.setattr(memory_loop, "_BANK", ExplodingBank())

    memory_loop.persist_turn("session-a", "hello", "hi there")

    from memory import load_session

    messages = load_session("session-a")
    assert [(row["role"], row["content"]) for row in messages] == [
        ("user", "hello"),
        ("assistant", "hi there"),
    ]


def test_inject_context_skips_vector_recall_by_default(monkeypatch):
    memory_loop = _fresh_memory_loop(monkeypatch)
    monkeypatch.setattr(memory_loop, "_BANK", ExplodingBank())

    memory_loop.persist_turn("session-b", "remember this", "saved")
    injected = memory_loop.inject_context("session-b", "what do you remember?")

    assert {"role": "user", "content": "remember this"} in injected
    assert not any("Relevant long-term memory" in row.get("content", "") for row in injected)


def test_vector_memory_opt_in_stores_and_recalls(monkeypatch):
    memory_loop = _fresh_memory_loop(monkeypatch)
    bank = RecordingBank()
    monkeypatch.setenv("METIS_CHAT_VECTOR_MEMORY", "1")
    monkeypatch.setattr(memory_loop, "_BANK", bank)

    memory_loop.persist_turn("session-c", "status style", "short")
    injected = memory_loop.inject_context("session-c", "status")

    assert len(bank.stores) == 1
    assert len(bank.searches) == 1
    assert any("Director prefers concise status updates." in row["content"] for row in injected)
