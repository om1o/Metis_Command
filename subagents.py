"""
Subagent spawner — Claude Code / Cursor-style one-shot specialized agents.

Use when the Director wants a targeted task delegated to a particular role
without routing through the full 5-agent swarm. Each subagent gets its own
tool pack and runs until it returns an answer or hits the step cap.

Available subagent types (mapped to brain_engine roles):
    - explorer   : scholar (read-only, wide context)
    - coder      : coder   (read+write+shell+sandbox)
    - researcher : researcher (web + browser)
    - thinker    : thinker (pure reasoning)
    - manager    : manager (delegates to others)

Returns a `SubagentResult` with the final text + tool-call transcript.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from brain_engine import chat_by_role
from safety import audit


@dataclass
class SubagentResult:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    subagent_type: str = "explorer"
    goal: str = ""
    answer: str = ""
    ok: bool = True
    duration_ms: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SUBAGENT_ROLES: dict[str, str] = {
    "explorer":   "scholar",
    "coder":      "coder",
    "researcher": "researcher",
    "thinker":    "thinker",
    "manager":    "manager",
}


def _roster_role(slug: str) -> str | None:
    """Resolve a role via the agent roster for data-driven subagent names."""
    try:
        import agent_roster
        spec = agent_roster.get(slug)
        return spec.role if spec else None
    except Exception:
        return None


def spawn(
    subagent_type: str,
    goal: str,
    *,
    readonly: bool = False,
    context: str = "",
    max_steps: int = 6,
) -> SubagentResult:
    """
    Run a one-shot subagent of the given type against `goal`.

    `readonly=True` forces the subagent to stay in pure-reasoning mode and
    skips any write-side tool calls — useful for the "explorer" type.
    """
    key = subagent_type.lower()
    role = SUBAGENT_ROLES.get(key) or _roster_role(key) or "manager"
    started = time.time()
    audit({"event": "subagent_spawn", "type": subagent_type, "role": role, "goal": goal[:120]})

    # Billing: each summon costs 1¢ against the Orchestrator Wallet so abuse
    # is observable.  `try_charge` is a no-op if the wallet is unavailable.
    try:
        from wallet import try_charge
        try_charge("subagent", 1, memo=f"spawn:{subagent_type}", subject=subagent_type)
    except Exception:
        pass

    if key in _SUBAGENT_SYSTEMS:
        system = _SUBAGENT_SYSTEMS[key]
    else:
        try:
            import agent_roster as _ar
            spec = _ar.get(key)
            system = (spec.system if spec else "") or _SUBAGENT_SYSTEMS["manager"]
        except Exception:
            system = _SUBAGENT_SYSTEMS["manager"]
    if readonly:
        system += "\n\nStrictly read-only: do not call write_file, edit_file, shell, or any tool that mutates state."

    user = f"GOAL: {goal}\n\n"
    if context:
        user += f"CONTEXT:\n{context}\n\n"
    user += "Provide a direct, concise final answer."

    # For coder/researcher we route through the autonomous_loop so tool-use works.
    if subagent_type.lower() in ("coder", "researcher") and not readonly:
        try:
            from autonomous_loop import run_mission
            mission = run_mission(goal, max_steps=max_steps, auto_approve=False)
            return SubagentResult(
                subagent_type=subagent_type,
                goal=goal,
                answer=mission.final_answer,
                ok=mission.status == "success",
                duration_ms=int((time.time() - started) * 1000),
                tool_calls=[{"step": s.index, "tool": s.tool, "args": s.args,
                             "ok": s.ok, "observation": str(s.observation)[:400]}
                            for s in mission.steps],
            )
        except Exception as e:
            audit({"event": "subagent_loop_failed", "error": str(e)})
            # Fall through to plain chat.

    # Plain reasoning path for explorer / thinker / readonly runs.
    answer = chat_by_role(role, [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ])
    return SubagentResult(
        subagent_type=subagent_type,
        goal=goal,
        answer=answer or "",
        ok=bool(answer),
        duration_ms=int((time.time() - started) * 1000),
    )


_SUBAGENT_SYSTEMS: dict[str, str] = {
    "explorer": (
        "You are a read-only codebase explorer. Given a question, locate the "
        "relevant file(s), describe what they do, and cite `path:line` when you "
        "can. Never propose edits — only report findings."
    ),
    "coder": (
        "You are a staff software engineer subagent. Implement the goal with "
        "type hints and docstrings. Prefer surgical edits. Validate changes by "
        "running the sandbox after every write."
    ),
    "researcher": (
        "You are a world-class web researcher subagent. Use the internet_search "
        "and browser tools to gather current, cited facts. Reject anything older "
        "than 12 months unless explicitly allowed."
    ),
    "thinker": (
        "You are a pure reasoning subagent. Lay out assumptions, enumerate paths, "
        "self-critique, then pick. Do not call any tools — just think."
    ),
    "manager": (
        "You are a manager subagent. Decide whether the task needs delegation. "
        "If delegation is needed, respond with a brief plan. Otherwise answer directly."
    ),
}
