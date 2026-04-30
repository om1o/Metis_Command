"""
Autonomous Task Loop — Manus-style goal-driven executor.

The Director gives a high-level goal. Metis:
    1. PLANS    — Thinker drafts a numbered step list.
    2. EXECUTES — for each step, Manager picks a tool + args, tool runs.
    3. OBSERVES — output feeds back into context.
    4. ADAPTS   — Thinker re-plans if a step fails or a better path emerges.
    5. FINISHES — when the goal is met, returns a summary + artifact bundle.

Every tool call is audited. Every step emits a structured event the UI
surfaces as a live tool-call card. Safety tools (shell, fs-write, browser
submit) still go through their confirm gates — the loop proposes, the
Director approves (or can flip `auto_approve` for trusted tasks).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from brain_engine import chat_by_role
from safety import audit, confirm_gate, ConfirmRequired
from tool_runtime import SessionExecutionLog, ToolRunner


# ── Public registry of atomic tools ──────────────────────────────────────────
# The autonomous loop only invokes tools listed here. Anything else the LLM
# proposes gets rejected. Keeps the surface area tight and auditable.

def _tool_registry() -> dict[str, Callable[..., Any]]:
    reg: dict[str, Callable[..., Any]] = {}
    from tools import file_system as _fs
    from tools import code_interpreter as _ci
    from tools import file_parser as _fp
    from tools import shell as _sh
    from tools import browser_agent as _ba
    from tools import computer_use as _cu
    from tools import voice_io as _vo
    from custom_tools import internet_search as _search

    from tools import multi_lang as _ml
    from subagents import spawn as _spawn_subagent

    reg.update({
        "read_file":         _fs.read_file,
        "write_file":        _fs.write_file,
        "edit_file":         _fs.edit_file,
        "list_dir":          _fs.list_dir,
        "grep":              _fs.grep,
        "find_files":        _fs.find_files,
        "parse_file":        _fp.parse,
        "python":            _ci.run,
        "run_code":          _ml.run,                                  # multi-language eval
        "shell":             lambda cmd: _sh.run(cmd, confirm=False),
        "browser_goto":      _ba.goto,
        "browser_click":     _ba.click,
        "browser_fill":      _ba.fill,
        "browser_extract":   _ba.extract,
        "browser_screenshot": _ba.screenshot,
        "screenshot":        _cu.screenshot,
        "speak":             _vo.speak,
        "web_search": lambda query: _search.run(query) if hasattr(_search, "run") else _search(query),
        "subagent":          lambda subagent_type, goal, readonly=False: _spawn_subagent(
                                 subagent_type, goal, readonly=readonly).to_dict(),
    })
    return reg


_TOOL_REGISTRY: dict[str, Callable[..., Any]] | None = None


def tool_registry() -> dict[str, Callable[..., Any]]:
    global _TOOL_REGISTRY
    if _TOOL_REGISTRY is None:
        _TOOL_REGISTRY = _tool_registry()
    return _TOOL_REGISTRY


# ── Data types ───────────────────────────────────────────────────────────────

@dataclass
class Step:
    index: int
    description: str
    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    observation: Any = None
    ok: bool = False
    duration_ms: int = 0


@dataclass
class Mission:
    goal: str
    steps: list[Step] = field(default_factory=list)
    final_answer: str = ""
    status: str = "pending"   # pending | running | success | failed | stopped
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None


# ── Prompts ──────────────────────────────────────────────────────────────────

PLANNER_SYSTEM = """
You are Metis's planner. Turn the Director's goal into a numbered list of
5-10 concrete steps that a tool-using agent can execute. Each step is ONE
tool call (the executor will pick the tool).  Be specific; avoid vague
steps like "investigate". Prefer reading files before editing them.

Respond with a JSON array of strings, nothing else. Example:
["Read app.py to understand the entry point",
 "Search for the bug in error.py",
 "Edit error.py to fix the null check"]
"""

EXECUTOR_SYSTEM = """
You are Metis's tool-use executor. Given the current step description and
the list of available tools, respond with ONE JSON object choosing the
tool to run, nothing else.

Valid tools (name -> signature):
  read_file(path)                       -> str
  write_file(path, content)             -> dict     (confirm-gated outside workspace)
  edit_file(path, old_string, new_string, replace_all=False)
  list_dir(path='.', depth=1)
  grep(pattern, path='.')
  find_files(glob_pattern, path='.')
  parse_file(path)
  python(code)                          -> dict     (pandas/numpy/matplotlib preloaded)
  shell(cmd)                            -> dict     (allowlisted only)
  browser_goto(url)
  browser_click(target)
  browser_fill(selector, value)
  browser_extract(selector=None)
  browser_screenshot()
  screenshot()
  speak(text)
  web_search(query)                     -> str

Respond like:
{"tool": "grep", "args": {"pattern": "def run_agentic", "path": "."}}

If the step is a pure reasoning step that needs no tool, respond:
{"tool": "none", "note": "explanation"}
"""

REFLECTOR_SYSTEM = """
You are Metis's progress reviewer. Given the goal, the plan, and the
observations so far, decide whether to:
  - continue with the current next step
  - replace the remaining plan with a better one
  - finish early because the goal is met

Respond with a JSON object:
{"decision": "continue"}                              OR
{"decision": "replan", "steps": ["new step A", "B", ...]}  OR
{"decision": "finish", "answer": "final answer"}
"""


# ── Loop ─────────────────────────────────────────────────────────────────────

def run_mission(
    goal: str,
    *,
    max_steps: int = 12,
    auto_approve: bool = False,
    on_event: Callable[[dict], None] | None = None,
    cancel=None,
    session_id: str | None = None,
) -> Mission:
    """
    Execute a goal as a plan -> execute -> reflect loop.

    If `cancel` is a CancelToken (or anything with `.cancelled`), the loop
    checks before each step and exits cleanly with status='stopped'.
    """
    mission = Mission(goal=goal, status="running")
    audit({"event": "mission_start", "goal": goal, "max_steps": max_steps})
    _emit(on_event, {"type": "mission_start", "goal": goal})

    def _is_cancelled() -> bool:
        return bool(cancel is not None and getattr(cancel, "cancelled", False))

    # 1. PLAN
    plan = _plan(goal)
    for i, desc in enumerate(plan, 1):
        mission.steps.append(Step(index=i, description=desc))
    _emit(on_event, {"type": "plan", "steps": plan})

    i = 0
    while i < len(mission.steps) and i < max_steps:
        if _is_cancelled():
            mission.status = "stopped"
            _emit(on_event, {"type": "cancelled", "step": i})
            break

        step = mission.steps[i]
        i += 1
        _emit(on_event, {"type": "step_start", "step": step.index,
                         "description": step.description})

        decision = _choose_tool(step.description)
        if not decision:
            step.ok = False
            step.observation = "executor returned no decision"
            _emit(on_event, {"type": "step_end", "step": step.index, "ok": False,
                             "error": step.observation})
            continue
        step.tool = decision.get("tool") or "none"
        step.args = decision.get("args") or {}

        if step.tool == "none":
            step.ok = True
            step.observation = decision.get("note", "thought-only step")
            _emit(on_event, {"type": "step_end", "step": step.index, "ok": True,
                             "tool": "none", "observation": step.observation})
        else:
            step.observation, step.ok, step.duration_ms = _run_tool(
                step.tool, step.args,
                auto_approve=auto_approve, on_event=on_event,
                cancel=cancel,
                session_id=session_id,
            )
            _emit(on_event, {"type": "step_end", "step": step.index,
                             "ok": step.ok, "tool": step.tool,
                             "duration_ms": step.duration_ms,
                             "observation_preview": str(step.observation)[:300]})

        # 3. REFLECT every 2 steps (and after failures)
        if not step.ok or step.index % 2 == 0:
            verdict = _reflect(mission)
            if verdict.get("decision") == "finish":
                mission.final_answer = verdict.get("answer", "")
                mission.status = "success"
                _emit(on_event, {"type": "finish", "answer": mission.final_answer})
                break
            if verdict.get("decision") == "replan":
                new_steps = verdict.get("steps") or []
                mission.steps = mission.steps[:i] + [
                    Step(index=i + k + 1, description=s)
                    for k, s in enumerate(new_steps)
                ]
                _emit(on_event, {"type": "replan", "new_steps": new_steps})

    if mission.status == "running":
        mission.final_answer = _synthesize(mission)
        mission.status = "success" if any(s.ok for s in mission.steps) else "failed"

    mission.ended_at = time.time()
    audit({"event": "mission_end", "status": mission.status,
           "steps": len(mission.steps), "goal": goal})
    _emit(on_event, {"type": "mission_end", "status": mission.status,
                     "answer": mission.final_answer})
    return mission


# ── Planner / Executor / Reflector LLM calls ─────────────────────────────────

_JSON_OBJ = re.compile(r"\{[\s\S]*\}")
_JSON_ARR = re.compile(r"\[[\s\S]*\]")


def _plan(goal: str) -> list[str]:
    reply = chat_by_role("thinker", [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user", "content": f"GOAL: {goal}"},
    ])
    m = _JSON_ARR.search(reply or "")
    if m:
        try:
            return [str(x) for x in json.loads(m.group(0))][:12]
        except Exception:
            pass
    return [line.strip("- ") for line in (reply or "").splitlines() if line.strip()][:10]


def _choose_tool(step_desc: str) -> dict[str, Any] | None:
    reg_names = ", ".join(sorted(tool_registry().keys()))
    reply = chat_by_role("manager", [
        {"role": "system", "content": EXECUTOR_SYSTEM},
        {"role": "user", "content":
            f"STEP: {step_desc}\n\nAVAILABLE TOOLS: {reg_names}\n\nReturn one JSON object."},
    ])
    m = _JSON_OBJ.search(reply or "")
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _run_tool(
    name: str,
    args: dict[str, Any],
    *,
    auto_approve: bool,
    on_event: Callable[[dict], None] | None,
    cancel=None,
    session_id: str | None = None,
) -> tuple[Any, bool, int]:
    """
    Invoke one tool with per-call budget.

    - Bails immediately if the CancelToken is set.
    - Enforces a hard wall-clock budget via a background thread.  The tool
      itself runs synchronously; if it hasn't returned within
      METIS_TOOL_TIMEOUT_S (default 120s) we surface a timeout observation
      so the executor can re-plan.
    """
    reg = tool_registry()
    if name not in reg:
        return f"unknown tool: {name}", False, 0

    if cancel is not None and getattr(cancel, "cancelled", False):
        return "cancelled before tool started", False, 0

    # ToolRunner emits tool_start/tool_end/error events for the UI, validates args,
    # supports retry/backoff, and persists a per-session tool run log.
    log = SessionExecutionLog(session_id) if session_id else None
    runner = ToolRunner(reg, on_event=on_event, session_log=log)

    # Keep confirm-gate semantics: a destructive tool can raise ConfirmRequired.
    def _wrapped(**kw: Any) -> Any:
        try:
            return reg[name](**kw)
        except ConfirmRequired as cr:
            if not auto_approve:
                raise
            token = str(cr)
            return reg[name](**{**kw, "confirm_token": token})

    tmp_reg = {**reg, name: _wrapped}
    runner.registry = tmp_reg

    res = runner.run(
        name,
        args,
        agent="manager",
        cancel_token=cancel,
        timeout_s=None,
        max_retries=1,
    )

    if res.confirm_required:
        _emit(on_event, {"type": "confirm_required", "tool": name, "token": res.confirm_token, "args": args})
        return {"confirm_required": True, "token": res.confirm_token}, False, res.duration_ms

    if not res.ok:
        return res.error or "tool failed", False, res.duration_ms
    return res.data, True, res.duration_ms


def _reflect(mission: Mission) -> dict[str, Any]:
    done = [s for s in mission.steps if s.observation is not None]
    summary = "\n".join(
        f"{s.index}. [{('ok' if s.ok else 'fail')}] {s.tool}({s.args}) -> "
        f"{str(s.observation)[:300]}"
        for s in done[-6:]
    )
    reply = chat_by_role("thinker", [
        {"role": "system", "content": REFLECTOR_SYSTEM},
        {"role": "user", "content":
            f"GOAL: {mission.goal}\n\nPROGRESS:\n{summary}\n\nRespond with JSON."},
    ])
    m = _JSON_OBJ.search(reply or "")
    if not m:
        return {"decision": "continue"}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"decision": "continue"}


def _synthesize(mission: Mission) -> str:
    summary = "\n".join(
        f"{s.index}. {s.tool}: {str(s.observation)[:200]}" for s in mission.steps
    )
    reply = chat_by_role("thinker", [
        {"role": "system", "content":
            "Summarize what was accomplished in 4-6 sentences, then list any "
            "follow-ups."},
        {"role": "user", "content":
            f"GOAL: {mission.goal}\n\nSTEPS:\n{summary}"},
    ])
    return reply or "Mission complete."


def _emit(on_event: Callable[[dict], None] | None, payload: dict) -> None:
    if on_event is None:
        return
    try:
        on_event(payload)
    except Exception:
        pass
