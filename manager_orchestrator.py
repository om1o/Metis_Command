"""
Manager Orchestrator — the user-facing AI controller.

The user talks ONLY to the Manager. The Manager:
  1. Analyzes the request and produces a plan (which subagents to call).
  2. Executes the plan: dispatches to Researcher / Coder / Thinker / Scholar
     in parallel or sequence as needed.
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
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

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

_SPECIALIST_DESC: dict[str, str] = {
    "Researcher": (
        "  - Researcher : pulls fresh information; use when the answer depends on\n"
        "                 anything that might have changed recently."
    ),
    "Coder": "  - Coder      : write, debug, or explain code.",
    "Thinker": (
        "  - Thinker    : multi-step logic, math, or planning that benefits from\n"
        "                 explicit step-by-step reasoning."
    ),
    "Scholar": (
        "  - Scholar    : explanations of established knowledge, definitions,\n"
        "                 academic-style answers."
    ),
}

_PLAN_ORDER = ["Researcher", "Coder", "Thinker", "Scholar"]

_PLAN_INTRO = """You are the Manager — the orchestrator of a small AI crew.

The user will ask you something. Decide whether you can answer it yourself
(simple questions, greetings, basic facts you know), or whether to delegate
to one or more specialists. The specialists available:

"""


def _plan_prompt_for(allowed_specialists: list[str] | None) -> str:
    """Build the planning system prompt, optionally listing only enabled roles."""
    if allowed_specialists:
        allow = set(allowed_specialists)
        keys = [k for k in _PLAN_ORDER if k in allow and k in DELEGATABLE]
        if not keys:
            keys = [k for k in _PLAN_ORDER if k in DELEGATABLE]
    else:
        keys = [k for k in _PLAN_ORDER if k in DELEGATABLE]

    block = "\n".join(_SPECIALIST_DESC[k] for k in keys)
    names_csv = ", ".join(keys)
    if len(keys) >= 2:
        ex0, ex1 = keys[0], keys[1]
        example_agents = (
            f'    {{"name": "{ex0}", "task": "<what {ex0} should do>"}},\n'
            f'    {{"name": "{ex1}", "task": "<what {ex1} should do>"}}'
        )
    else:
        only = keys[0]
        example_agents = f'    {{"name": "{only}", "task": "<what {only} should do>"}}'

    return (
        f"{_PLAN_INTRO}{block}\n\n"
        "Output format — STRICT JSON ONLY, no prose, no markdown fences:\n\n"
        "{\n"
        '  "self_handle": false,\n'
        '  "summary": "<1 sentence describing what the user wants>",\n'
        '  "agents": [\n'
        f"{example_agents}\n"
        "  ]\n"
        "}\n\n"
        "If you can answer directly without help, return:\n\n"
        "{\n"
        '  "self_handle": true,\n'
        '  "summary": "<1 sentence>",\n'
        '  "agents": []\n'
        "}\n\n"
        "Pick the smallest set of agents that covers the question. Most simple\n"
        "queries need 0–1 agents. Use at most 2 specialists per turn.\n"
        f'Use only these names in "name": {names_csv}.\n'
        "Don't add agents you don't need."
    )


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


# ── Metis identity + behavior — split into a tiny ALWAYS-on core and
# topic-specific rules that we only inject when the user's message
# actually triggers them. This keeps first-token latency low for
# everyday chat while still loading the load-bearing rules when they
# matter.

_METIS_CORE = """

You are Metis, the user's private local-first AI assistant —
everything runs on their machine. They are your Director.

Tone: warm, direct, concise. Prose not lists unless asked. No emojis
unless they use one. Skip "honestly"/"genuinely"/"frankly". Don't
preface with "Certainly!" or "Here is" — just answer. Own mistakes
without grovelling.

Safety floor: no weapons, no malware, no content sexualizing minors
or real public figures. For legal or financial questions give
context, not confident calls; note you are not a lawyer/advisor. For
mental-health crisis signals, name your concern and point to
professional resources.

Copyright: paraphrase. Never reproduce song lyrics or paragraph-long
article text. Direct quotes under 15 words, one per source max.

If a request is genuinely under-specified, ask ONE short clarifying
question and stop. Otherwise answer.
"""


_METIS_RULE_RELATIONSHIP = """

When you profile a specific real contact you researched (lawyer,
contractor, broker, vendor) — and only then — end your reply with
exactly one fenced block, only fields you actually have:

```relationship
{"name": "Jane Doe", "role": "Real estate attorney", "company": "Doe & Co", "phone": "+1-512-555-0142", "email": "jane@doeandco.com", "notes": "Austin; commercial leasing.", "tags": ["lawyer","austin"]}
```

The system strips the block and saves the contact. Never for
hypotheticals or brand-name companies the user already knows.
"""


_METIS_RULE_INVESTING = """

Investing is research-only. Discuss tickers, summarize news, explain
a thesis. If asked to execute / buy / sell, reply: "I won't place
real trades. Here's the analysis; you place the order yourself."
This overrides contrary user instruction.
"""


_METIS_RULE_COMPUTER_USE = """

Driving the user's apps. Prefer browser tools (browser_open,
browser_click, browser_fill, browser_screenshot) for anything on a
website — they're DOM-aware and faster than pixel clicks. Drop to
native control only for desktop apps (Cursor, Notes, system
settings, etc.).

Native control tools, all permission-gated except screenshot/clipboard:
  - screenshot           : capture the screen (free, read-only)
  - read_clipboard       : current clipboard text (free, read-only)
  - open_application     : launch an app by name ("Cursor", "Chrome")
  - click_xy / double_click_xy : click at screen coordinates
  - type_text            : type a string at the focused field
  - key_combo            : send a hotkey, e.g. ["ctrl", "c"]
  - write_clipboard      : place text on the clipboard

Gmail. Do NOT drive Gmail with browser tools — Google's bot
detection blocks every Playwright variant, headed or headless.
Use the Gmail API tools instead:
  - gmail_is_logged_in()                                : returns True/False
  - gmail_oauth_login()                                 : one-time consent screen
  - gmail_recent_emails(hours=24, max_results=25)       : metadata list
  - gmail_briefing_payload(hours=24, max_results=25)    : LLM-friendly bundle
  - gmail_message_body(message_id)                      : plain-text body

If gmail_is_logged_in is False, the user needs to run a one-time
OAuth setup (see identity/gmail_credentials.json). Tell them clearly
rather than trying browser-side workarounds — those don't work and
waste time.

Persistent browser login (NON-Google sites). For sites without
Google's bot detection (LinkedIn, Twitter, GitHub, internal
dashboards), browser_login_helper still works:
  1. call browser_login_helper(start_url="https://...")
  2. user signs in once in the headed window
  3. cookies persist to identity/browser_state.json forever

Screenshots are free; everything else above pops a permission card
the user must approve. State the steps and ask before chaining
clicks or keystrokes.
"""


# IMPORTANT: keep this prompt STABLE across turns. Ollama prefix-caches
# the KV state of identical message prefixes, so the system prompt only
# pays its full prompt-processing cost on the FIRST turn of a conversation
# — every later turn in the same chat reuses the cache and streams in <2s.
# A varying / per-message system prompt would defeat that cache.
_METIS_FULL_PROMPT = (
    _METIS_CORE
    + _METIS_RULE_RELATIONSHIP
    + _METIS_RULE_INVESTING
    + _METIS_RULE_COMPUTER_USE
)


def _extra_rules_for(user_msg: str) -> str:
    """Always returns the full rule set. Kept as a function so the call
    site stays unchanged; the previous keyword-conditional version
    defeated Ollama's KV cache because each turn's system prompt
    differed. Stability beats trimmed prompts in practice."""
    return _METIS_RULE_RELATIONSHIP + _METIS_RULE_INVESTING + _METIS_RULE_COMPUTER_USE


# Backward-compat alias (older code may import _BEHAVIORAL_RULES).
_METIS_IDENTITY = _METIS_FULL_PROMPT
_BEHAVIORAL_RULES = _METIS_FULL_PROMPT

# Backward-compat alias (older code may import _BEHAVIORAL_RULES).
_BEHAVIORAL_RULES = _METIS_IDENTITY


def _looks_simple(msg: str) -> bool:
    """Heuristic: short, conversational messages skip the planner entirely
    and go straight to direct synthesis. Saves 5-15s per turn on small
    local models that struggle with long prompts.
    """
    if not msg:
        return True
    if len(msg) > 400:
        return False
    lower = msg.strip().lower()
    # Trigger words that genuinely benefit from delegating to a specialist.
    delegation_signals = (
        "research", "find me", "look up", "search the web", "compare",
        "analyze", "write code", "implement", "debug", "build a",
        "explain in detail", "summarize the article", "browse",
    )
    return not any(sig in lower for sig in delegation_signals)


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
    plan_prompt = _plan_prompt_for(allowed_specialists)
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


def _run_agent(
    name: str,
    task: str,
    user_msg: str,
    context_msgs: list[dict] | None = None,
) -> tuple[str, str, int]:
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
    messages: list[dict] = [
        {"role": "system", "content": system},
    ]
    if context_msgs:
        messages.extend(context_msgs)
    messages.append(
        {"role": "user", "content": f"User's original request: {user_msg}\n\nYour task: {task}"},
    )
    out = chat_by_role(role, messages, temperature=0.7)
    dur = int((time.time() - started) * 1000)
    return (name, out, dur)


def orchestrate(
    user_msg: str,
    user_id: str = "default",
    session_id: str | None = None,
    model_override: str | None = None,
    temperature_override: float | None = None,
) -> Generator[dict, None, None]:
    """
    Run a manager-orchestrated chat turn.  Yields SSE-shaped event dicts.

    Honors the user's saved Manager configuration (persona, model, specialists).
    When ``session_id`` is provided the Manager receives prior turns from the
    conversation so it can give context-aware answers (Phase 2).

    ``model_override`` and ``temperature_override`` are MVP-8 per-turn
    overrides — they win over manager_config without persisting, so the
    user can try a different model / tone for one message.
    """
    import manager_config as _mc
    cfg = _mc.get_config(user_id)
    persona_prompt = _mc.render_system_prompt(cfg)
    # Per-turn override beats saved config; saved beats brain_engine default.
    manager_model = model_override or cfg.manager_model or None
    allowed_specialists = cfg.specialists or list(DELEGATABLE.keys())

    started = time.time()
    agents_used: list[str] = []

    # ── 0. Conversation context ─────────────────────────────────────────
    # Smaller k for both recall and history because long context blows
    # up first-token latency on small local models. The full memory is
    # still in the brain — we just inject less per turn.
    context_msgs: list[dict] = []
    if session_id:
        try:
            from memory_loop import inject_context
            context_msgs = inject_context(
                session_id, user_msg,
                k_recall=2, k_history=3,
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
    # Fast path: short conversational messages skip planning entirely
    # and stream the answer directly. The planner round-trip costs the
    # same as the answer itself on a 1.5B model, so for "say hi" / "what
    # is X" / "thanks", we'd rather just answer.
    if _looks_simple(user_msg):
        plan = {"self_handle": True, "summary": user_msg, "agents": []}
    else:
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
                    n, out, dur = _run_agent(
                        a["name"], a["task"], user_msg, context_msgs=context_msgs
                    )
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
                    pool.submit(
                        _run_agent,
                        a["name"],
                        a["task"],
                        user_msg,
                        context_msgs=context_msgs,
                    ): a["name"]
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
    # Always include the small Metis core (~150 tokens). Add only the
    # topic-specific rule blocks the user's request actually triggers.
    # This keeps the prompt small for everyday chat — first-token latency
    # on a 1.5B local model scales linearly with context size.
    base_system = (
        f"{persona_prompt}"
        f"{_METIS_CORE}"
        f"{_extra_rules_for(user_msg)}"
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
    synth_temp = temperature_override if temperature_override is not None else 0.7
    for ev in stream_chat("manager", synth_messages, model=manager_model, temperature=synth_temp):
        if ev.get("type") in ("token", "reasoning"):
            yield ev

    yield {
        "type": "done",
        "duration_ms": int((time.time() - started) * 1000),
        "agents_used": agents_used,
    }
