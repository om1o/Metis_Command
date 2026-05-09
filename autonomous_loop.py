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
from pydantic import ValidationError

from tool_runtime import SessionExecutionLog, ToolRunner, ToolSpec, build_pydantic_model_from_callable


# ── Public registry of atomic tools ──────────────────────────────────────────
# The autonomous loop only invokes tools listed here. Anything else the LLM
# proposes gets rejected. Keeps the surface area tight and auditable.

def _tool_registry() -> dict[str, Callable[..., Any]]:
    """Atomic tools the LLM is allowed to propose during a mission.

    State-changing tools (writes, shell, browser actions, native-app
    clicks/typing) are wrapped through ``permissions.gate``. The wrapper
    consults the active session's tier:
      * ``read``     → instant deny
      * ``balanced`` → block until user clicks Approve / Deny
      * ``full``     → pass-through

    Read-only tools (read_file, grep, parse_file, web_search,
    screenshot) skip the gate.
    """
    reg: dict[str, Callable[..., Any]] = {}
    from tools import file_system as _fs
    from tools import code_interpreter as _ci
    from tools import file_parser as _fp
    from tools import shell as _sh
    from tools import browser_agent as _ba
    from tools import computer_use as _cu
    from tools import voice_io as _vo
    from tools import gmail_api as _gm
    from tools import vision as _vis
    from custom_tools import internet_search as _search

    from tools import multi_lang as _ml
    from subagents import spawn as _spawn_subagent
    import permissions as _perm

    reg.update({
        # Read-only / observational — no gate.
        "read_file":          _fs.read_file,
        "list_dir":           _fs.list_dir,
        "grep":               _fs.grep,
        "find_files":         _fs.find_files,
        "parse_file":         _fp.parse,
        "browser_extract":    _ba.extract,
        "browser_screenshot": _ba.screenshot,
        "screenshot":         _cu.screenshot,
        "web_search": lambda query: _search.run(query) if hasattr(_search, "run") else _search(query),

        # MVP 17: vision. The agent SEES the screen. Both tools read
        # an image path and return descriptions / coordinates — no
        # state change, so no gate needed. The pattern is:
        #   1. screenshot()                    -> path
        #   2. vision_find_element(path, "X")  -> {x, y, found}
        #   3. click_xy(x, y)                  -> gated; user approves
        # Vision routes through brain_engine.chat_by_role("vision"),
        # which uses Ollama's llava locally and cloud vision when keys
        # are set.
        "vision_describe":     lambda image_path, prompt=None: _vis.describe(
                                   str(image_path), prompt=prompt),
        "vision_find_element": lambda image_path, description: _vis.find_element(
                                   str(image_path), str(description)),
        "see_then_click":      lambda image_path, target: _vis.see_then_click(
                                   str(image_path), str(target)),

        # State-changing — gated through Read/Balanced/Full.
        "write_file":   _perm.gate("write_file",   _fs.write_file,                    summary_args=["path"]),
        "edit_file":    _perm.gate("edit_file",    _fs.edit_file,                     summary_args=["path"]),
        "python":       _perm.gate("python",       _ci.run,                           summary_args=["code"]),
        "run_code":     _perm.gate("run_code",     _ml.run,                           summary_args=["language", "code"]),
        "shell":        _perm.gate("shell",        lambda cmd: _sh.run(cmd, confirm=False), summary_args=["cmd"]),
        "browser_goto": _perm.gate("browser_goto", _ba.goto,                          summary_args=["url"]),
        "browser_click": _perm.gate("browser_click", _ba.click,                       summary_args=["target"]),
        "browser_fill": _perm.gate("browser_fill", _ba.fill,                          summary_args=["selector", "value"]),
        # MVP 18a: semantic click/fill — natural language not CSS.
        # Walks role/label/placeholder/text strategies in priority
        # order with auto-retry on stale-element races.
        "browser_click_smart": _perm.gate("browser_click_smart", _ba.click_smart, summary_args=["target"]),
        "browser_fill_smart":  _perm.gate("browser_fill_smart",  _ba.fill_smart,  summary_args=["label", "value"]),
        "speak":        _perm.gate("speak",        _vo.speak,                         summary_args=["text"]),

        # MVP 15: real desktop control. The internal confirm flag in
        # tools/computer_use is bypassed here (confirm=False) because
        # the permission gate is the authoritative fence — Read tier
        # blocks these instantly, Balanced asks the user, Full lets
        # them run. open_application is the "go-to-app" entrypoint
        # for "open my Cursor" / "open Gmail in browser" requests.
        "click_xy":     _perm.gate("click_xy",
                                   lambda x, y, button="left": _cu.click_xy(int(x), int(y), button=button, confirm=False),
                                   summary_args=["x", "y"]),
        "double_click_xy": _perm.gate("double_click_xy",
                                      lambda x, y: _cu.double_click_xy(int(x), int(y), confirm=False),
                                      summary_args=["x", "y"]),
        "type_text":    _perm.gate("type_text",
                                   lambda text, interval=0.02: _cu.type_text(text, interval=float(interval), confirm=False),
                                   summary_args=["text"]),
        "key_combo":    _perm.gate("key_combo",
                                   lambda keys: _cu.key_combo(list(keys) if not isinstance(keys, list) else keys, confirm=False),
                                   summary_args=["keys"]),
        "write_clipboard": _perm.gate("write_clipboard", _cu.write_clipboard, summary_args=["text"]),
        "read_clipboard": _cu.read_clipboard,  # read-only
        "open_application": _perm.gate("open_application", _cu.open_application, summary_args=["name"]),
        # Persistent-browser helpers — snapshot/clear cookies so a
        # one-time Gmail login stays usable across sessions. The
        # save itself is gated (touches disk); login_helper opens a
        # HEADED browser and is gated for the same reason.
        "browser_save_state":  _perm.gate("browser_save_state",  _ba.save_state),
        "browser_clear_state": _perm.gate("browser_clear_state", _ba.clear_state),
        "browser_login_helper": _perm.gate("browser_login_helper", _ba.login_helper, summary_args=["start_url"]),

        # MVP 16: Gmail via OAuth + Gmail API. Browser automation
        # against Gmail loses to Google's bot detection every time;
        # OAuth wins. oauth_login pops Google's official consent
        # screen (which works in any browser) and saves a refresh
        # token; everything else is silent thereafter.
        "gmail_oauth_login":     _perm.gate("gmail_oauth_login",     _gm.oauth_login),
        "gmail_logout":          _perm.gate("gmail_logout",          _gm.logout),
        "gmail_is_logged_in":    _gm.is_logged_in,                                       # read-only
        "gmail_recent_emails":   lambda hours=24, max_results=25: _gm.to_dicts(
                                     _gm.list_recent(hours=int(hours), max_results=int(max_results))),
        "gmail_briefing_payload": lambda hours=24, max_results=25: _gm.briefing_payload(
                                     hours=int(hours), max_results=int(max_results)),
        "gmail_message_body":    lambda message_id, max_chars=4000: _gm.get_body(
                                     str(message_id), max_chars=int(max_chars)),

        # Subagents recursively run their own loop; their internal tools
        # inherit the same permission tier via the session emitter, so
        # we don't need to gate the spawn itself.
        "subagent": lambda subagent_type, goal, readonly=False: _spawn_subagent(
            subagent_type, goal, readonly=readonly).to_dict(),
    })
    return reg


_TOOL_REGISTRY: dict[str, Callable[..., Any]] | None = None


def tool_registry() -> dict[str, Callable[..., Any]]:
    global _TOOL_REGISTRY
    if _TOOL_REGISTRY is None:
        _TOOL_REGISTRY = _tool_registry()
    return _TOOL_REGISTRY


_MUTATING_TOOLS = {
    "write_file",
    "edit_file",
    "shell",
    "browser_click",
    "browser_fill",
    "browser_click_smart",
    "browser_fill_smart",
    "speak",
    "subagent",
    # MVP 15 — anything that touches the real desktop or browser cookies.
    "click_xy",
    "double_click_xy",
    "type_text",
    "key_combo",
    "write_clipboard",
    "open_application",
    "browser_save_state",
    "browser_clear_state",
    "browser_login_helper",
    "python",
    "run_code",
    "browser_goto",
}

_READ_ONLY_GOAL = re.compile(
    r"(^|\b)(find|read|inspect|search|summarize|list|locate|tell me|what is|show me)\b",
    re.IGNORECASE,
)
_PACKAGE_JSON_PATH = re.compile(r"([A-Za-z0-9_.\\/-]*package\.json)", re.IGNORECASE)


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
  # Files / search — read-only is free
  read_file(path)                       -> str
  list_dir(path='.', depth=1)
  grep(pattern, path='.')
  find_files(glob_pattern, path='.')
  parse_file(path)
  write_file(path, content)             -> dict     (gated)
  edit_file(path, old_string, new_string, replace_all=False)   (gated)

  # Code / shell — gated
  python(code)                          -> dict     (pandas/numpy/matplotlib preloaded)
  run_code(language, code)              -> dict     (multi-language)
  shell(cmd)                            -> dict     (allowlisted only)

  # Browser (Playwright, headless by default) — actions gated
  browser_goto(url)                     (gated)
  browser_click(target)                 (gated; raw CSS or text)
  browser_fill(selector, value)         (gated; raw CSS)
  browser_click_smart(target)           (gated; "Submit" / "Sign in" / etc.)
  browser_fill_smart(label, value)      (gated; field by label/placeholder)
  browser_extract(selector=None)        -> str
  browser_screenshot()                  -> path
  browser_save_state()                  (gated; snapshot cookies)
  browser_clear_state()                 (gated; wipe cookies)
  browser_login_helper(start_url)       (gated; HEADED browser for one-time login)

  # Native desktop — vision is free, control is gated
  screenshot()                          -> path
  read_clipboard()                      -> str
  write_clipboard(text)                 (gated)
  open_application(name)                (gated; "Cursor", "Chrome", etc.)
  click_xy(x, y, button='left')         (gated)
  double_click_xy(x, y)                 (gated)
  type_text(text, interval=0.02)        (gated)
  key_combo(keys)                       (gated; e.g. ["ctrl","c"])

  # Vision — describe what's on screen / find UI elements
  vision_describe(image_path)               -> str
  vision_find_element(image_path, desc)     -> {found, x, y, confidence}
  see_then_click(image_path, target)        -> click-ready payload (no click)

  # Misc
  speak(text)                           (gated)
  web_search(query)                     -> str

Respond like:
{"tool": "grep", "args": {"pattern": "def run_agentic", "path": "."}}

For Gmail / Twitter / LinkedIn etc., the headless browser starts
without cookies. If a step needs to read the user's signed-in
state, propose browser_login_helper FIRST with the provider's
login URL — that opens a headed browser the user signs into once,
and the cookies persist for later runs.

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

    if _run_deterministic_mission_if_possible(
        mission,
        auto_approve=auto_approve,
        on_event=on_event,
        cancel=cancel,
        session_id=session_id,
    ):
        mission.ended_at = time.time()
        audit({"event": "mission_end", "status": mission.status,
               "steps": len(mission.steps), "goal": goal})
        _emit(on_event, {"type": "mission_end", "status": mission.status,
                         "answer": mission.final_answer})
        return mission

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

        decision = _choose_tool(step.description, goal=goal)
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

        exact_answer = _deterministic_final_answer(mission).strip()
        if exact_answer:
            mission.final_answer = exact_answer
            mission.status = "success"
            _emit(on_event, {"type": "finish", "answer": mission.final_answer})
            break

        # 3. REFLECT every 2 steps (and after failures)
        if not step.ok or step.index % 2 == 0:
            verdict = _reflect(mission)
            if verdict.get("decision") == "finish":
                answer = str(verdict.get("answer", "")).strip()
                if _goal_needs_deterministic_answer(mission.goal) and not _deterministic_final_answer(mission).strip():
                    answer = ""
                if answer:
                    mission.final_answer = answer
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
        if any(_step_has_useful_success(s) for s in mission.steps):
            mission.final_answer = _deterministic_final_answer(mission).strip() or _synthesize(mission).strip()
            mission.status = "success" if mission.final_answer else "failed"
        else:
            mission.final_answer = "Unable to complete the goal with the executed steps."
            mission.status = "failed"

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
    heuristic = _heuristic_plan(goal)
    if heuristic:
        return heuristic

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


def _heuristic_plan(goal: str) -> list[str]:
    lower = (goal or "").lower()
    if "package.json" in lower and (
        "package name" in lower
        or "package version" in lower
        or "version string" in lower
    ):
        matches = _PACKAGE_JSON_PATH.findall(goal)
        if matches:
            path = matches[0].replace("\\", "/").lstrip("./")
            return [f"Read {path}"]
    return []


def _run_deterministic_mission_if_possible(
    mission: Mission,
    *,
    auto_approve: bool,
    on_event: Callable[[dict], None] | None,
    cancel=None,
    session_id: str | None = None,
) -> bool:
    plan = _heuristic_plan(mission.goal)
    if not plan:
        return False
    _emit(on_event, {"type": "plan", "steps": plan})
    step = Step(index=1, description=plan[0], tool="read_file")
    path = plan[0].replace("Read ", "", 1)
    step.args = {"path": path}
    mission.steps.append(step)
    _emit(on_event, {"type": "step_start", "step": step.index, "description": step.description})
    step.observation, step.ok, step.duration_ms = _run_tool(
        step.tool,
        step.args,
        auto_approve=auto_approve,
        on_event=on_event,
        cancel=cancel,
        session_id=session_id,
    )
    _emit(on_event, {"type": "step_end", "step": step.index,
                     "ok": step.ok, "tool": step.tool,
                     "duration_ms": step.duration_ms,
                     "observation_preview": str(step.observation)[:300]})
    answer = _deterministic_final_answer(mission).strip()
    if answer:
        mission.final_answer = answer
        mission.status = "success"
        _emit(on_event, {"type": "finish", "answer": mission.final_answer})
    else:
        mission.final_answer = "Unable to complete the goal with the executed steps."
        mission.status = "failed"
    return True


def _choose_tool(step_desc: str, *, goal: str = "") -> dict[str, Any] | None:
    heuristic = _heuristic_tool_decision(step_desc, goal=goal)
    if heuristic is not None:
        return heuristic

    reg_names = ", ".join(sorted(tool_registry().keys()))
    messages = [
        {"role": "system", "content": EXECUTOR_SYSTEM},
        {"role": "user", "content":
            f"GOAL: {goal}\n\nSTEP: {step_desc}\n\nAVAILABLE TOOLS: {reg_names}\n\nReturn one JSON object."},
    ]
    last_decision: dict[str, Any] | None = None
    for _attempt in range(2):
        reply = chat_by_role("manager", messages)
        m = _JSON_OBJ.search(reply or "")
        if not m:
            return None
        try:
            decision = json.loads(m.group(0))
        except Exception:
            return None
        if not isinstance(decision, dict):
            return None
        last_decision = decision
        error = _tool_arg_error(decision.get("tool"), decision.get("args") or {}, goal=goal)
        if not error:
            return decision
        messages.append({"role": "assistant", "content": json.dumps(decision)})
        messages.append({"role": "user", "content":
            f"That tool call is invalid: {error}\n"
            "Return one corrected JSON object with every required argument."})
    return last_decision


def _heuristic_tool_decision(step_desc: str, *, goal: str = "") -> dict[str, Any] | None:
    text = f"{goal}\n{step_desc}"
    lower = text.lower()
    if "package.json" in lower and any(k in lower for k in ("package name", "read", "open", "load")):
        matches = _PACKAGE_JSON_PATH.findall(text)
        if matches:
            path = matches[0].replace("\\", "/").lstrip("./")
            return {"tool": "read_file", "args": {"path": path}}
    return None


def _step_has_useful_success(step: Step) -> bool:
    if not step.ok:
        return False
    if step.observation is None:
        return False
    if isinstance(step.observation, (list, tuple, dict, set)) and len(step.observation) == 0:
        return False
    if isinstance(step.observation, str) and step.observation.strip() in {"", "[]", "{}"}:
        return False
    return True


def _deterministic_final_answer(mission: Mission) -> str:
    goal = mission.goal.lower()
    if "package.json" in goal:
        field = ""
        if "package name" in goal:
            field = "name"
        elif "package version" in goal or "version string" in goal:
            field = "version"
        if not field:
            return ""
        for step in mission.steps:
            text = str(step.observation or "")
            match = re.search(rf'"{re.escape(field)}"\s*:\s*"([^"]+)"', text)
            if match:
                return match.group(1)
    return ""


def _goal_needs_deterministic_answer(goal: str) -> bool:
    text = goal.lower()
    return "package.json" in text and (
        "package name" in text
        or "package version" in text
        or "version string" in text
    )


def _is_read_only_goal(goal: str) -> bool:
    text = (goal or "").strip()
    return "Permission: Read-only" in text or bool(_READ_ONLY_GOAL.search(text))


def _tool_arg_error(tool: Any, args: Any, *, goal: str = "") -> str | None:
    name = str(tool or "none")
    if name == "none":
        return None
    if name in _MUTATING_TOOLS and _is_read_only_goal(goal):
        return f"tool {name} is not allowed for this read-only goal"
    reg = tool_registry()
    if name not in reg:
        return f"unknown tool: {name}"
    if not isinstance(args, dict):
        return "args must be an object"
    try:
        model = build_pydantic_model_from_callable(reg[name], name)
        model.model_validate(args)
    except ValidationError as ve:
        return f"validation_error: {ve.errors(include_url=False)}"
    except Exception as e:
        return f"validation_error: {e}"
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
    input_model = None
    try:
        input_model = build_pydantic_model_from_callable(reg[name], name)
    except Exception:
        input_model = None
    specs = {name: ToolSpec(name=name, input_model=input_model)} if input_model is not None else None
    runner = ToolRunner(reg, specs=specs, on_event=on_event, session_log=log)

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
