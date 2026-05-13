"""
Manager Orchestrator — the user-facing AI controller.

The user talks ONLY to the Manager. The Manager:
  1. Analyzes the request and produces a plan (which subagents to call).
  2. Executes the plan: dispatches to Genius / Researcher / Coder / Thinker /
     Scholar in parallel or sequence as needed.
  3. Synthesizes the subagent outputs into a single coherent answer.

The orchestrator emits structured events the UI streams as SSE so the
operator sees exactly what is happening:

    {"type": "manager_plan",     "summary": str, "agents": [str, ...]}
    {"type": "agent_start",      "agent": str, "task": str}
    {"type": "agent_thought",    "agent": str, "delta": str}
    {"type": "agent_done",       "agent": str, "output": str, "duration_ms": int}
    {"type": "manager_synthesis"}            # Manager begins writing final answer
    {"type": "token",            "delta": str}       # Final answer tokens
    {"type": "reasoning",        "delta": str}       # Manager's reasoning (hidden)
    {"type": "done",             "duration_ms": int, "agents_used": [str, ...]}
    {"type": "error",            "message": str}
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Generator

from brain_engine import chat_by_role, stream_chat


# Specialists the Manager can delegate to. Keys are user-friendly names;
# values are brain_engine role names. "Genius" is intentionally NOT here —
# the heavyweight cloud brain is a *model choice* the operator makes for the
# Manager itself, not a separate specialist they see in the crew.
DELEGATABLE: dict[str, str] = {
    "Researcher": "researcher",  # web + retrieval
    "Coder":      "coder",       # code-heavy tasks
    "Thinker":    "thinker",     # deep reasoning (deepseek-r1)
    "Scholar":    "scholar",     # knowledge / explanations
}


# spawn_agents path uses stream_chat for synthesis after agent completion
_PLAN_PROMPT = """You are the Manager — the orchestrator of a small AI crew.

The user will ask you something. Decide whether you can answer it yourself
(simple questions, greetings, basic facts you know), or whether to delegate
to one or more specialists. The specialists available:

  - Researcher : pulls fresh information; use when the answer depends on
                 anything that might have changed recently.
  - Coder      : write, debug, or explain code.
  - Thinker    : multi-step logic, math, or planning that benefits from
                 explicit step-by-step reasoning.
  - Scholar    : explanations of established knowledge, definitions,
                 academic-style answers.

Output format — STRICT JSON ONLY, no prose, no markdown fences:

{
  "self_handle": false,
  "summary": "<1 sentence describing what the user wants>",
  "agents": [
    {"name": "Genius",     "task": "<what Genius should do>"},
    {"name": "Researcher", "task": "<what Researcher should do>"}
  ]
}

If you can answer directly without help, return:

{
  "self_handle": true,
  "summary": "<1 sentence>",
  "agents": []
}

Pick the smallest set of agents that covers the question. Most simple
queries need 0–1 agents. Use at most 2 specialists per turn.
Don't add agents you don't need.

Additionally, include a "spawn_agents" key in your JSON output.
Set "spawn_agents": true when the task requires tool-equipped sub-agents
(coding, file manipulation, research with web access, or testing).
Set "spawn_agents": false for simple questions and conversational responses."""


_SYNTHESIS_PROMPT = """You are the Manager. You delegated parts of the
user's request to specialist agents and now have their outputs. Compose
a single, polished final answer for the user.

User's original request:
{user_msg}

Specialist outputs:
{outputs}

Write the final answer directly. Be concise but complete. Do NOT mention
the specialists by name — speak in your own voice. Do NOT preface with
"based on" or "according to". Just answer."""


def _extract_json(text: str) -> dict | None:
    """Best-effort JSON extraction from a model response."""
    text = (text or "").strip()
    # Strip code fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    # Find first { ... last }
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _build_plan(
    user_msg: str,
    allowed_specialists: list[str] | None = None,
    model: str | None = None,
    context_msgs: list[dict] | None = None,
) -> dict[str, Any]:
    """Ask the Manager (small fast model) to produce a delegation plan."""
    # Trim the planning prompt to only the specialists the user enabled.
    plan_prompt = _PLAN_PROMPT
    if allowed_specialists:
        # Build a filtered specialists block
        registry = {
            "Researcher": "Researcher : pulls fresh information; use when the answer depends on anything that might have changed recently.",
            "Coder":      "Coder      : write, debug, or explain code.",
            "Thinker":    "Thinker    : multi-step logic, math, or planning that benefits from explicit step-by-step reasoning.",
            "Scholar":    "Scholar    : explanations of established knowledge, definitions, academic-style answers.",
        }
        lines = [f"  - {registry[k]}" for k in allowed_specialists if k in registry]
        if lines:
            specialists_block = "\n".join(lines)
            plan_prompt = (
                _PLAN_PROMPT.split("The specialists available:")[0]
                + "The specialists available:\n\n" + specialists_block + "\n\n"
                + _PLAN_PROMPT.split("Output format")[1].rsplit("Output format", 0)[0]
                if False else _PLAN_PROMPT  # keep original if rebuilding fails
            )
    messages: list[dict] = [
        {"role": "system", "content": plan_prompt},
    ]
    # Inject prior conversation context so the planner can see multi-turn history.
    if context_msgs:
        messages.extend(context_msgs)
    messages.append({"role": "user", "content": user_msg})
    raw = chat_by_role("manager", messages, model=model, temperature=0.1)
    plan = _extract_json(raw) or {"self_handle": True, "summary": user_msg, "agents": []}
    # Normalize
    plan.setdefault("self_handle", True)
    plan.setdefault("summary", user_msg)
    plan.setdefault("agents", [])
    # Filter to known + allowed agents
    allowed = set(allowed_specialists) if allowed_specialists else set(DELEGATABLE.keys())
    plan["agents"] = [
        a for a in plan["agents"]
        if isinstance(a, dict) and a.get("name") in DELEGATABLE and a.get("name") in allowed
    ][:2]  # cap at 2 to bound latency + cost
    if not plan["agents"]:
        plan["self_handle"] = True
    return plan


def _run_agent(name: str, task: str, user_msg: str) -> tuple[str, str, int]:
    """Run one specialist agent. Returns (name, output, duration_ms)."""
    role = DELEGATABLE[name]
    started = time.time()
    system = (
        f"You are {name}, a specialist working under a Manager. "
        f"Your specific task: {task}. "
        f"Reply with ONLY your contribution — concise, focused, no preamble. "
        f"The Manager will synthesize multiple specialist outputs into the "
        f"final answer to the user, so don't address the user directly."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": f"User's original request: {user_msg}\n\nYour task: {task}"},
    ]
    out = chat_by_role(role, messages, temperature=0.7)
    dur = int((time.time() - started) * 1000)
    return (name, out, dur)


def orchestrate(
    user_msg: str,
    user_id: str = "default",
    session_id: str | None = None,
) -> Generator[dict, None, None]:
    """
    Run a manager-orchestrated chat turn.  Yields SSE-shaped event dicts.

    Honors the user's saved Manager configuration (persona, model, specialists).
    When ``session_id`` is provided the Manager receives prior turns from the
    conversation so it can give context-aware answers (Phase 2).
    """
    import manager_config as _mc
    cfg = _mc.get_config(user_id)
    persona_prompt = _mc.render_system_prompt(cfg)
    manager_model = cfg.manager_model or None  # None → brain_engine default
    allowed_specialists = cfg.specialists or list(DELEGATABLE.keys())

    started = time.time()
    agents_used: list[str] = []

    # ── 0. Conversation context ─────────────────────────────────────────
    # Inject prior turns + vector memories so the Manager has multi-turn
    # awareness.  Falls back to empty list if anything goes wrong.
    context_msgs: list[dict] = []
    if session_id:
        try:
            from memory_loop import inject_context
            context_msgs = inject_context(
                session_id, user_msg,
                k_recall=5, k_history=6,
                user_id=user_id,
            )
        except Exception:
            context_msgs = []

    # Surface the active persona so the UI can show name/avatar in real time.
    yield {
        "type":         "manager_identity",
        "manager_name": cfg.manager_name,
        "company_name": cfg.company_name,
        "accent_color": cfg.accent_color,
        "model":        manager_model,
    }

    # ── 1. Plan ──────────────────────────────────────────────────────────
    try:
        plan = _build_plan(
            user_msg, allowed_specialists,
            model=manager_model,
            context_msgs=context_msgs,
        )
    except Exception as e:
        yield {"type": "error", "message": f"Manager planning failed: {e}"}
        return

    yield {
        "type":    "manager_plan",
        "summary": plan.get("summary", ""),
        "agents":  [a["name"] for a in plan.get("agents", [])],
        "self_handle": bool(plan.get("self_handle")),
    }

    # ── 2. Execute specialists ──────────────────────────────────────────
    # If the plan requests tool-equipped sub-agents, delegate to agent_spawner.
    if plan.get("spawn_agents"):
        from agent_spawner import run_task
        project_dir = str(Path(__file__).resolve().parent)
        gen = run_task(
            task=user_msg,
            job_id=None,
            project_dir=project_dir,
            sandbox_roots=[project_dir],
        )
        spawn_summary = ""
        for ev in gen:
            yield ev
            if ev.get("type") == "task_complete":
                spawn_summary = ev.get("summary", "")
                agents_used = ev.get("agents_used", [])

        # Synthesize the spawned-agent output through the Manager
        synth_prompt = (
            f"The agents completed the task. Here's what they did:\n\n"
            f"{spawn_summary}\n\n"
            f"Synthesize this into a clear response for the user."
        )
        synth_messages = [
            {"role": "system", "content": persona_prompt},
        ]
        if context_msgs:
            synth_messages.extend(context_msgs)
        synth_messages.append({"role": "user", "content": synth_prompt})

        yield {"type": "manager_synthesis", "role": "manager"}
        try:
            for ev in stream_chat("manager", synth_messages, model=manager_model):
                if ev.get("type") in ("token", "reasoning"):
                    yield ev
        except Exception as e:
            yield {"type": "error", "message": f"Synthesis failed: {e}"}
        finally:
            yield {
                "type": "done",
                "duration_ms": int((time.time() - started) * 1000),
                "agents_used": agents_used,
            }
        return

    # Sequential by default. Local Ollama can only fit so many models in VRAM
    # at once; running 4 specialists in parallel triggers heavy model
    # swapping that produces 60-180s timeouts on a typical 8GB GPU.
    # Operators with huge VRAM (or cloud-only setups) can flip this via env
    # var without redeploying.
    outputs: list[tuple[str, str, int]] = []   # (name, output, ms)
    if not plan.get("self_handle") and plan.get("agents"):
        agent_specs = plan["agents"]
        max_parallel = max(1, int(os.getenv("METIS_AGENT_PARALLELISM", "1")))

        # Announce starts up-front so the UI can render all cards.
        for a in agent_specs:
            yield {"type": "agent_start", "agent": a["name"], "task": a["task"]}

        if max_parallel <= 1 or len(agent_specs) == 1:
            # Sequential — predictable, no VRAM thrashing.
            for a in agent_specs:
                try:
                    n, out, dur = _run_agent(a["name"], a["task"], user_msg)
                except Exception as e:
                    n, out, dur = a["name"], f"[{a['name']} failed: {e}]", 0
                outputs.append((n, out, dur))
                agents_used.append(n)
                yield {
                    "type": "agent_done",
                    "agent": n,
                    "output": out,
                    "duration_ms": dur,
                }
        else:
            with ThreadPoolExecutor(max_workers=min(max_parallel, len(agent_specs))) as pool:
                futures = {
                    pool.submit(_run_agent, a["name"], a["task"], user_msg): a["name"]
                    for a in agent_specs
                }
                for fut in as_completed(futures):
                    name = futures[fut]
                    try:
                        n, out, dur = fut.result()
                    except Exception as e:
                        n, out, dur = name, f"[{name} failed: {e}]", 0
                    outputs.append((n, out, dur))
                    agents_used.append(n)
                    yield {
                        "type": "agent_done",
                        "agent": n,
                        "output": out,
                        "duration_ms": dur,
                    }

    # ── 3. Synthesis: Manager streams the final answer ───────────────────
    base_system = (
        f"{persona_prompt}\n\n"
        "Answer in your own voice. Do NOT preface your answer with phrases "
        "like 'Certainly!', 'Here is', 'Based on', or 'The final answer'. "
        "Just answer."
    )

    # Build the message list: system → context history → current question.
    synth_messages: list[dict] = [{"role": "system", "content": base_system}]
    if context_msgs:
        synth_messages.extend(context_msgs)

    if outputs:
        joined = "\n\n".join(f"### {n}\n{o}" for n, o, _ in outputs)
        synth_msg = _SYNTHESIS_PROMPT.format(user_msg=user_msg, outputs=joined)
        synth_messages.append({"role": "user", "content": synth_msg})
    else:
        synth_messages.append({"role": "user", "content": user_msg})

    yield {"type": "manager_synthesis", "role": "manager"}
    try:
        for ev in stream_chat("manager", synth_messages, model=manager_model):
            if ev.get("type") in ("token", "reasoning"):
                yield ev
    except Exception as e:
        yield {"type": "error", "message": f"Synthesis failed: {e}"}
    finally:
        yield {
            "type": "done",
            "duration_ms": int((time.time() - started) * 1000),
            "agents_used": agents_used,
        }
