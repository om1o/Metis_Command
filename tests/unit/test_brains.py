"""Brains CRUD + compact safety."""

from __future__ import annotations


def test_create_list_get_delete(brains_module):
    b = brains_module.create("Pytest")
    assert b.slug == "pytest"
    assert any(x.slug == "pytest" for x in brains_module.list_brains())
    assert brains_module.get("pytest") is not None
    assert brains_module.delete("pytest") is True
    assert brains_module.get("pytest") is None


def test_active_brain_roundtrip(brains_module):
    b = brains_module.create("Scratch")
    brains_module.switch(b.slug)
    assert brains_module.active_slug() == b.slug
    brains_module.delete(b.slug)


def test_compact_bails_on_empty_summary(brains_module, monkeypatch):
    """Guarantee: never delete sources when the LLM returns nothing useful."""
    import brain_engine
    b = brains_module.create("Compact")
    try:
        for i in range(60):
            brains_module.remember(f"durable fact #{i}", kind="semantic", brain=b)
        monkeypatch.setattr(brain_engine, "chat_by_role", lambda *a, **k: "")
        folded = brains_module.compact(brain=b, window=40)
        assert folded == 0
        # Short single-line replies also rejected.
        monkeypatch.setattr(brain_engine, "chat_by_role", lambda *a, **k: "ok")
        folded = brains_module.compact(brain=b, window=40)
        assert folded == 0
    finally:
        brains_module.delete(b.slug)


def test_compact_accepts_good_summary(brains_module, monkeypatch):
    import brain_engine
    b = brains_module.create("CompactGood")
    try:
        for i in range(60):
            brains_module.remember(f"durable fact #{i}", kind="semantic", brain=b)
        good = (
            "- The Director prefers Python\n"
            "- Uses Windows daily\n"
            "- Likes concise answers without filler\n"
            "- Works on Metis Command most days"
        )
        monkeypatch.setattr(brain_engine, "chat_by_role", lambda *a, **k: good)
        folded = brains_module.compact(brain=b, window=40)
        assert folded > 0
        # Trash file should exist - nothing is truly lost.
        trash = brains_module._brain_dir(b.slug) / "compact_trash.jsonl"
        assert trash.exists()
        assert trash.stat().st_size > 0
    finally:
        brains_module.delete(b.slug)
