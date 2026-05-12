"""
Agent spawner — creates ephemeral tool-equipped agents for tasks.

The Manager calls run_task() which:
1. Analyzes the task to decide which roles are needed
2. Spawns agents sequentially (to respect rate limits)
3. Each agent runs a tool-calling loop (max 10 iterations)
4. Agents communicate via a shared thread
5. Manager synthesizes final answer
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Generator

from agent_models import chat, pick_model
from agent_prompts import get_prompt
from agent_tools import TOOL_SCHEMAS, execute_tool


@dataclass
class AgentThread:
    """Shared communication context for a group of agents."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    messages: list[dict] = field(default_factory=list)
    max_rounds: int = 10

    def post(self, sender: str, content: str) -> None:
        self.messages.append({"from": sender, "content": content, "ts": time.time()})

    def context_str(self) -> str:
        """Format thread messages for injection into agent prompts."""
        if not self.messages:
            return ""
        lines = []
        for m in self.messages[-20:]:  # last 20 messages
            lines.append(f"[{m['from']}]: {m['content'][:500]}")
        return "\n\n--- Team Thread ---\n" + "\n".join(lines)


def _run_agent(
    role: str,
    task: str,
    thread: AgentThread,
    sandbox_roots: list[str],
    project_dir: str | None = None,
) -> Generator[dict, None, str]:
    """Run one agent through its tool-calling loop. Yields SSE events. Returns final output."""
    model, provider = pick_model(role)
    system_prompt = get_prompt(role, task, project_dir)

    yield {"type": "agent_spawned", "agent": role, "model": model, "provider": provider}

    messages = [{"role": "system", "content": system_prompt}]

    # Inject thread context if available
    thread_ctx = thread.context_str()
    if thread_ctx:
        messages.append({"role": "system", "content": thread_ctx})

    messages.append({"role": "user", "content": task})

    # Determine if this model supports tool calling
    # Not all free models do — fallback to prompt-based tools
    use_tools = provider == "openrouter" and ":free" in model

    final_output = ""

    for iteration in range(thread.max_rounds):
        resp = chat(role, messages, tools=TOOL_SCHEMAS if use_tools else None)
        content = resp.get("content", "")
        tool_calls = resp.get("tool_calls", [])

        if tool_calls:
            # Execute each tool call
            messages.append({"role": "assistant", "content": content, "tool_calls": [
                {"id": tc["id"], "type": "function", "function": tc["function"]}
                for tc in tool_calls
            ]})

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    fn_args = {}

                yield {"type": "agent_tool", "agent": role, "tool": fn_name, "args": fn_args}

                result = execute_tool(fn_name, fn_args, sandbox_roots)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
        else:
            # No tool calls — this is the agent's final response
            final_output = content
            break

    if not final_output:
        final_output = content or "[Agent produced no output]"

    thread.post(role, final_output)
    yield {"type": "agent_complete", "agent": role, "output": final_output[:500], "model": model}

    return final_output


def _decide_roles(task: str) -> list[str]:
    """Simple heuristic to decide which agent roles are needed."""
    lower = task.lower()
    roles = []

    # Always plan first for complex tasks
    if any(w in lower for w in ["build", "create", "implement", "design", "make", "add"]):
        roles.append("planner")

    # Code-related
    if any(w in lower for w in ["code", "write", "build", "implement", "create", "function", "class", "api", "fix"]):
        roles.append("coder")

    # Debug-related
    if any(w in lower for w in ["debug", "fix", "error", "bug", "crash", "broken"]):
        roles.append("debugger")

    # Test-related
    if any(w in lower for w in ["test", "verify", "check", "validate", "benchmark"]):
        roles.append("tester")

    # Research-related
    if any(w in lower for w in ["research", "find", "search", "look up", "what is", "how to", "explain"]):
        roles.append("researcher")

    # Default: at least use a coder
    if not roles:
        roles = ["coder"]

    return roles


def run_task(
    task: str,
    job_id: str | None = None,
    project_dir: str | None = None,
    sandbox_roots: list[str] | None = None,
) -> Generator[dict, None, dict]:
    """
    Main entry point — Manager calls this to spawn agents for a task.

    Yields SSE events. Returns final summary dict.
    """
    if sandbox_roots is None:
        sandbox_roots = [project_dir] if project_dir else ["."]

    roles = _decide_roles(task)
    thread = AgentThread()

    yield {"type": "task_start", "task": task[:100], "roles": roles, "job_id": job_id}

    # Update job status if applicable
    if job_id:
        try:
            from memory import update_job_status
            update_job_status(job_id, "running")
        except Exception:
            pass

    agents_used = []
    all_outputs = {}

    for role in roles:
        agent_gen = _run_agent(role, task, thread, sandbox_roots, project_dir)
        output = ""
        # Consume generator, forwarding events
        try:
            while True:
                ev = next(agent_gen)
                yield ev
        except StopIteration as e:
            output = e.value or ""

        agents_used.append(role)
        all_outputs[role] = output

    # Synthesize summary
    summary_parts = []
    for role, output in all_outputs.items():
        summary_parts.append(f"**{role.title()}:** {output[:300]}")
    summary = "\n\n".join(summary_parts)

    # Update job status
    if job_id:
        try:
            from memory import update_job_status
            update_job_status(job_id, "completed")
        except Exception:
            pass

    yield {"type": "task_complete", "summary": summary[:1000], "agents_used": agents_used, "job_id": job_id}

    return {"summary": summary, "agents_used": agents_used, "thread": thread.messages}
