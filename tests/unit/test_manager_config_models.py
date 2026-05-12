"""Manager model discovery ordering."""

from __future__ import annotations


def test_available_models_prefers_fast_manager_model(monkeypatch):
    import brain_engine
    import manager_config

    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        brain_engine,
        "list_local_models",
        lambda: ["qwen3.5:4b", "qwen2.5-coder:7b", "qwen2.5-coder:1.5b"],
    )

    models = manager_config.list_available_models()

    assert [model["id"] for model in models] == [
        "qwen2.5-coder:1.5b",
        "qwen2.5-coder:7b",
        "qwen3.5:4b",
    ]
    assert "recommended fast" in models[0]["note"]
    assert "experimental slow" in models[-1]["note"]


def test_available_models_prefers_configured_cloud_before_local(monkeypatch):
    import brain_engine
    import manager_config

    monkeypatch.setattr(brain_engine, "list_local_models", lambda: ["qwen2.5-coder:1.5b"])
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.delenv("GLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    models = manager_config.list_available_models()

    assert models[0]["id"].startswith("groq/")
    assert models[1]["id"] == "qwen2.5-coder:1.5b"
