"""Safety / file_lock / PATHS tests."""

from __future__ import annotations

import threading
import time

import pytest


def test_paths_exist(_sandbox_paths):
    import safety
    assert safety.PATHS.logs.exists()
    assert safety.PATHS.identity.exists()


def test_secret_scan_catches_openai_key():
    from safety import redact, secret_scan
    src = "my token is sk-proj-" + "a" * 30
    hits = secret_scan(src)
    assert any(h["kind"] == "openai" for h in hits)
    assert "[REDACTED:openai]" in redact(src)


def test_secret_scan_is_clean_on_benign_text():
    from safety import secret_scan
    assert secret_scan("hello world, nothing sensitive here") == []


def test_require_safe_path_allows_paths_under_paths_root(_sandbox_paths):
    from safety import require_safe_path

    target = _sandbox_paths / "allowed.txt"
    target.write_text("ok", encoding="utf-8")

    assert require_safe_path(target) == target.resolve()


def test_require_safe_path_allows_clean_relative_workspace_path():
    from safety import is_path_safe

    assert is_path_safe("desktop-ui/package.json") is True
    assert is_path_safe("../outside.txt") is False


def test_file_lock_is_exclusive():
    """Second acquirer must wait until the first releases."""
    from safety import file_lock
    held = threading.Event()
    release = threading.Event()
    order: list[str] = []

    def worker_a():
        with file_lock("safety_excl"):
            order.append("a-in")
            held.set()
            release.wait(timeout=3)
            order.append("a-out")

    t = threading.Thread(target=worker_a, daemon=True)
    t.start()
    assert held.wait(timeout=2)
    # At this moment A holds the lock.  A short-timeout B must TimeoutError.
    t0 = time.time()
    with pytest.raises(TimeoutError):
        with file_lock("safety_excl", timeout=0.3):
            pass
    elapsed = time.time() - t0
    assert 0.2 <= elapsed < 1.5
    order.append("b-timed-out")
    release.set()
    t.join(timeout=2)
    # A finished cleanly even after B gave up.
    assert order == ["a-in", "b-timed-out", "a-out"]


def test_audit_log_appends(_sandbox_paths):
    import json
    from safety import AUDIT_LOG, audit
    audit({"event": "pytest_ok", "value": 1})
    assert AUDIT_LOG.exists()
    rows = [json.loads(line) for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines()]
    assert any(r.get("event") == "pytest_ok" for r in rows)


def test_structured_log_verbose_env(capfd, monkeypatch):
    from safety import log
    monkeypatch.setenv("METIS_VERBOSE", "1")
    log("noisy_event", k=1)
    out, _err = capfd.readouterr()
    assert "noisy_event" in out
