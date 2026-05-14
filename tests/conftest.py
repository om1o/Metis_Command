"""
Pytest root conftest.

- Inserts the repo root on sys.path so tests can `import wallet` etc.
- Redirects PATHS.* to a tmp sandbox for every test so no test ever
  reads or writes the user's real identity/, logs/, or metis_db/ dirs.
- Provides a few shared fixtures (`wallet_env`, `brain_env`).
"""

from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _sandbox_paths(monkeypatch):
    """
    Redirect every state-path reference through an isolated temp directory
    before any production module uses it.  Each test gets its own sandbox.
    """
    base_tmp = ROOT / "artifacts" / "test-tmp"
    base_tmp.mkdir(parents=True, exist_ok=True)
    tmp = base_tmp / f"metis-test-{uuid.uuid4().hex[:12]}"
    tmp.mkdir()
    (tmp / "logs").mkdir()
    (tmp / "identity").mkdir()
    (tmp / "artifacts").mkdir()
    (tmp / "metis_db").mkdir()
    (tmp / "logs" / "locks").mkdir()

    import safety  # real module

    original = safety.PATHS
    monkeypatch.setattr(
        safety.PATHS,
        "root",
        tmp,
        raising=False,
    )
    monkeypatch.setattr(safety.PATHS, "logs", tmp / "logs", raising=False)
    monkeypatch.setattr(safety.PATHS, "identity", tmp / "identity", raising=False)
    monkeypatch.setattr(safety.PATHS, "artifacts", tmp / "artifacts", raising=False)
    monkeypatch.setattr(safety.PATHS, "metis_db", tmp / "metis_db", raising=False)
    monkeypatch.setattr(safety, "LOGS_DIR", tmp / "logs", raising=False)
    monkeypatch.setattr(safety, "AUDIT_LOG", tmp / "logs" / "audit.jsonl", raising=False)
    monkeypatch.setattr(safety, "_LOCK_DIR", tmp / "logs" / "locks", raising=False)

    # Clear any module-level singletons that captured the real paths.
    for mod_name in ("wallet", "scheduler", "brains", "auth_local"):
        if mod_name in sys.modules:
            del sys.modules[mod_name]

    yield tmp
    # Restore (monkeypatch already undoes; the tmp dir gets cleaned).
    _ = original
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def wallet_module(_sandbox_paths):
    """Fresh wallet module each test, pointed at the sandbox."""
    import importlib
    import wallet as _w
    importlib.reload(_w)
    return _w


@pytest.fixture
def brains_module(_sandbox_paths):
    import importlib
    import brains as _b
    importlib.reload(_b)
    return _b


@pytest.fixture
def fake_llm(monkeypatch):
    """Install a deterministic fake for brain_engine.chat_by_role."""
    import brain_engine
    replies: list[str] = []

    def _factory(reply: str) -> None:
        replies.append(reply)

    def _fake(role, messages, **_kw):  # noqa: ARG001
        return replies.pop(0) if replies else "fake reply"

    monkeypatch.setattr(brain_engine, "chat_by_role", _fake)
    return _factory


@pytest.fixture(autouse=True)
def _hush_env(monkeypatch):
    """Keep tests deterministic: no user env can leak into behaviour."""
    for key in (
        "METIS_VERBOSE", "METIS_MAX_WORKERS", "METIS_MAX_QUEUE",
        "METIS_TOOL_TIMEOUT_S", "METIS_STREAM_READ_TIMEOUT",
        "METIS_WALLET_MODE", "METIS_TIER_OVERRIDE",
        "GLM_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    # Keep OLLAMA_BASE pointed at localhost so accidental hits don't go
    # anywhere real.
    monkeypatch.setenv("OLLAMA_BASE", "http://127.0.0.1:11434")
    yield
