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


def test_unknown_tool_returns_clean_error(monkeypatch):
    import autonomous_loop
    monkeypatch.setattr(autonomous_loop, "tool_registry", lambda: {})
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


def test_choose_tool_retries_mutating_tool_for_read_only_goal(monkeypatch):
    import autonomous_loop

    def fake_edit(path: str, old_string: str, new_string: str) -> dict:
        return {"ok": True}

    def fake_read(path: str) -> str:
        return path

    replies = iter([
        '{"tool": "edit_file", "args": {"path": "x", "old_string": "a", "new_string": "b"}}',
        '{"tool": "read_file", "args": {"path": "desktop-ui/package.json"}}',
    ])

    monkeypatch.setattr(
        autonomous_loop,
        "tool_registry",
        lambda: {"edit_file": fake_edit, "read_file": fake_read},
    )
    monkeypatch.setattr(autonomous_loop, "chat_by_role", lambda *_args, **_kw: next(replies))

    decision = autonomous_loop._choose_tool(
        "Edit package.json if no entry point is found",
        goal="Find the package name in desktop-ui/package.json.",
    )

    assert decision == {"tool": "read_file", "args": {"path": "desktop-ui/package.json"}}


def test_empty_finish_after_failure_does_not_mark_success(monkeypatch):
    import autonomous_loop

    monkeypatch.setattr(autonomous_loop, "_plan", lambda _goal: ["bad step"])
    monkeypatch.setattr(autonomous_loop, "_choose_tool", lambda *_args, **_kw: {"tool": "bad", "args": {}})
    monkeypatch.setattr(
        autonomous_loop,
        "_run_tool",
        lambda *_args, **_kw: ("failed", False, 1),
    )
    monkeypatch.setattr(autonomous_loop, "_reflect", lambda _mission: {"decision": "finish", "answer": ""})
    monkeypatch.setattr(autonomous_loop, "_synthesize", lambda _mission: "")

    mission = autonomous_loop.run_mission("Find a value", max_steps=1)

    assert mission.status == "failed"
    assert mission.final_answer == "Unable to complete the goal with the executed steps."


def test_empty_success_observations_do_not_mark_mission_success(monkeypatch):
    import autonomous_loop

    monkeypatch.setattr(autonomous_loop, "_plan", lambda _goal: ["search"])
    monkeypatch.setattr(autonomous_loop, "_choose_tool", lambda *_args, **_kw: {"tool": "grep", "args": {"pattern": "x"}})
    monkeypatch.setattr(autonomous_loop, "_run_tool", lambda *_args, **_kw: ([], True, 1))
    monkeypatch.setattr(autonomous_loop, "_reflect", lambda _mission: {"decision": "continue"})
    monkeypatch.setattr(autonomous_loop, "_synthesize", lambda _mission: "fake success")

    mission = autonomous_loop.run_mission("Find a value", max_steps=1)

    assert mission.status == "failed"
    assert mission.final_answer == "Unable to complete the goal with the executed steps."


def test_package_json_goal_prefers_read_file_without_model_call(monkeypatch):
    import autonomous_loop

    def fail_chat(*_args, **_kw):
        raise AssertionError("model should not be needed for package.json read heuristic")

    monkeypatch.setattr(autonomous_loop, "chat_by_role", fail_chat)
    monkeypatch.setattr(autonomous_loop, "tool_registry", lambda: {"read_file": lambda path: path})

    decision = autonomous_loop._choose_tool(
        "Open desktop-ui/package.json using json.load()",
        goal="Find the package name in desktop-ui/package.json.",
    )

    assert decision == {"tool": "read_file", "args": {"path": "desktop-ui/package.json"}}


def test_package_json_exact_goal_uses_deterministic_plan(monkeypatch):
    import autonomous_loop

    def fail_chat(*_args, **_kw):
        raise AssertionError("planner model should not be needed for exact package.json lookup")

    monkeypatch.setattr(autonomous_loop, "chat_by_role", fail_chat)

    assert autonomous_loop._plan(
        "Find the package name in desktop-ui/package.json. Answer with only the package name.",
    ) == ["Read desktop-ui/package.json"]


def test_package_json_package_name_uses_tool_observation_not_synthesis(monkeypatch):
    import autonomous_loop

    monkeypatch.setattr(
        autonomous_loop,
        "_run_tool",
        lambda *_args, **_kw: ('     2|  "name": "desktop-ui",', True, 1),
    )

    def fail_synthesis(_mission):
        raise AssertionError("structured package-name answer should not use synthesis")

    monkeypatch.setattr(autonomous_loop, "_synthesize", fail_synthesis)

    mission = autonomous_loop.run_mission(
        "Find the package name in desktop-ui/package.json.",
        max_steps=1,
    )

    assert mission.status == "success"
    assert mission.final_answer == "desktop-ui"
    assert len(mission.steps) == 1


def test_package_json_version_finishes_immediately_from_tool_observation(monkeypatch):
    import autonomous_loop

    calls = []

    def fake_run_tool(*_args, **_kw):
        calls.append("run")
        return ('     3|  "version": "0.1.0",', True, 1)

    monkeypatch.setattr(autonomous_loop, "_run_tool", fake_run_tool)

    mission = autonomous_loop.run_mission(
        "Find the package version in desktop-ui/package.json. Answer with only the version string.",
        max_steps=3,
    )

    assert mission.status == "success"
    assert mission.final_answer == "0.1.0"
    assert calls == ["run"]


def test_exact_package_goal_rejects_ungrounded_reflector_finish(monkeypatch):
    import autonomous_loop

    monkeypatch.setattr(autonomous_loop, "_plan", lambda _goal: ["bad search"])
    monkeypatch.setattr(
        autonomous_loop,
        "_choose_tool",
        lambda *_args, **_kw: {"tool": "grep", "args": {"pattern": "missing"}},
    )
    monkeypatch.setattr(autonomous_loop, "_run_tool", lambda *_args, **_kw: ([], True, 1))
    monkeypatch.setattr(autonomous_loop, "_reflect", lambda _mission: {"decision": "finish", "answer": "final answer"})
    monkeypatch.setattr(autonomous_loop, "_synthesize", lambda _mission: "fake synthesis")

    mission = autonomous_loop.run_mission(
        "Find the package name in desktop-ui/package.json. Answer with only the package name.",
        max_steps=1,
    )

    assert mission.status == "failed"
    assert mission.final_answer == "Unable to complete the goal with the executed steps."


def test_audited_tools_keep_signatures_for_validation():
    import inspect
    from tools import file_system

    sig = inspect.signature(file_system.grep)

    assert "pattern" in sig.parameters
    assert sig.parameters["pattern"].default is inspect.Parameter.empty
