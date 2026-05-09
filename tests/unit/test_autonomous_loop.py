"""Autonomous loop cancel / tool timeout / narrow exception handling."""

from __future__ import annotations

import time


class _FakeCancel:
    """Drop-in replacement for brain_engine.CancelToken."""

    def __init__(self, fire_after: float | None = None) -> None:
        self._fire_after = fire_after
        self._start = time.time()

    @property
    def cancelled(self) -> bool:
        if self._fire_after is None:
            return False
        return (time.time() - self._start) >= self._fire_after


def test_run_mission_exits_clean_when_cancelled(monkeypatch):
    import autonomous_loop
    monkeypatch.setattr(autonomous_loop, "_plan",
                        lambda goal: ["step a", "step b"])
    ct = _FakeCancel(fire_after=0)  # already cancelled
    m = autonomous_loop.run_mission("noop", max_steps=3, cancel=ct)
    assert m.status == "stopped"


def test_tool_timeout_fires_without_hanging(monkeypatch):
    """If a tool sleeps forever, _run_tool must return a timeout string."""
    import autonomous_loop
    monkeypatch.setenv("METIS_TOOL_TIMEOUT_S", "0.2")

    def never_returns():
        time.sleep(5)
        return "never"

    monkeypatch.setattr(
        autonomous_loop, "tool_registry",
        lambda: {"sleepy": lambda: never_returns()},
    )
    t0 = time.time()
    obs, ok, _ms = autonomous_loop._run_tool(
        "sleepy", {}, auto_approve=False, on_event=None, cancel=None,
    )
    assert ok is False
    assert "timed out" in str(obs).lower()
    assert time.time() - t0 < 1.5


def test_tool_cancel_midway(monkeypatch):
    import autonomous_loop

    def slow():
        time.sleep(2)
        return "done"

    monkeypatch.setattr(autonomous_loop, "tool_registry",
                        lambda: {"slow": lambda: slow()})
    ct = _FakeCancel(fire_after=0.1)
    t0 = time.time()
    obs, ok, _ = autonomous_loop._run_tool(
        "slow", {}, auto_approve=False, on_event=None, cancel=ct,
    )
    assert ok is False
    assert "cancel" in str(obs).lower()
    assert time.time() - t0 < 1.5


def test_unknown_tool_returns_clean_error():
    import autonomous_loop
    obs, ok, _ = autonomous_loop._run_tool(
        "not_a_tool", {}, auto_approve=False, on_event=None, cancel=None,
    )
    assert ok is False
    assert "unknown tool" in obs


def test_run_tool_validates_original_signature_when_confirm_wrapped(monkeypatch):
    import autonomous_loop

    def needs_pattern(pattern: str) -> str:
        return pattern

    monkeypatch.setattr(
        autonomous_loop,
        "tool_registry",
        lambda: {"needs_pattern": needs_pattern},
    )

    obs, ok, _ = autonomous_loop._run_tool(
        "needs_pattern", {}, auto_approve=False, on_event=None, cancel=None,
    )

    assert ok is False
    assert "validation_error" in str(obs)
    assert "pattern" in str(obs)
    assert "TypeError" not in str(obs)


def test_choose_tool_retries_invalid_arguments(monkeypatch):
    import autonomous_loop

    def fake_grep(pattern: str, path: str = ".") -> list[str]:
        return [pattern, path]

    replies = iter([
        '{"tool": "grep", "args": {}}',
        '{"tool": "grep", "args": {"pattern": "needle", "path": "."}}',
    ])

    monkeypatch.setattr(autonomous_loop, "tool_registry", lambda: {"grep": fake_grep})
    monkeypatch.setattr(autonomous_loop, "chat_by_role", lambda *_args, **_kw: next(replies))

    decision = autonomous_loop._choose_tool("Search for needle")

    assert decision == {"tool": "grep", "args": {"pattern": "needle", "path": "."}}


def test_audited_tools_keep_signatures_for_validation():
    import inspect
    from tools import file_system

    sig = inspect.signature(file_system.grep)

    assert "pattern" in sig.parameters
    assert sig.parameters["pattern"].default is inspect.Parameter.empty
