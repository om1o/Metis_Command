"""
Agent spawner — creates ephemeral tool-equipped agents for tasks.

The Manager calls run_task() which:
1. Asks the Manager LLM to plan custom agents for the task
2. Spawns agents sequentially (to respect rate limits)
3. Each agent runs a tool-calling loop (max 10 iterations)
4. Agents communicate via a shared thread
5. Manager synthesizes final answer
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Generator

from agent_models import chat, pick_model
from agent_prompts import get_prompt, generate_agent_prompt
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
    agent_spec: dict,
    task: str,
    thread: AgentThread,
    sandbox_roots: list[str],
    project_dir: str | None = None,
) -> Generator[dict, None, str]:
    """Run one agent through its tool-calling loop. Yields SSE events. Returns final output.

    agent_spec is a dict with keys: name, role, tools (list of tool names).
    """
    agent_name = agent_spec["name"]
    agent_role_desc = agent_spec.get("role", "")
    agent_tools = agent_spec.get("tools", [])

    model, provider = pick_model("default")

    # Filter TOOL_SCHEMAS to only the tools this agent is allowed to use
    if agent_tools:
        filtered_schemas = [s for s in TOOL_SCHEMAS if s["function"]["name"] in agent_tools]
    else:
        filtered_schemas = TOOL_SCHEMAS

    system_prompt = generate_agent_prompt(
        role_name=agent_name,
        role_description=agent_role_desc,
        task=task,
        tools_available=agent_tools,
        project_dir=project_dir,
    )

    yield {"type": "agent_spawned", "agent": agent_name, "model": model, "provider": provider}

    messages = [{"role": "system", "content": system_prompt}]

    # Inject thread context if available
    thread_ctx = thread.context_str()
    if thread_ctx:
        messages.append({"role": "system", "content": thread_ctx})

    messages.append({"role": "user", "content": task})

    # Determine if this model supports tool calling
    use_tools = provider == "openrouter" and ":free" in model and filtered_schemas

    final_output = ""
    content = ""

    for iteration in range(thread.max_rounds):
        try:
            resp = chat("default", messages, tools=filtered_schemas if use_tools else None)
        except Exception as e:
            yield {"type": "agent_error", "agent": agent_name, "error": str(e)}
            final_output = f"[Agent {agent_name} crashed: {e}]"
            break
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

                yield {"type": "agent_tool", "agent": agent_name, "tool": fn_name, "args": fn_args}

                result = execute_tool(fn_name, fn_args, sandbox_roots)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
        else:
            # No tool calls — this is the agent's final response
            final_output = content
            break

    if not final_output:
        final_output = content or "[Agent produced no output]"

    thread.post(agent_name, final_output)
    yield {"type": "agent_complete", "agent": agent_name, "output": final_output[:500], "model": model}

    return final_output


def _plan_agents(task: str) -> list[dict]:
    """Ask the Manager to plan which custom agents to create.

    Returns list of dicts: [{"name": "Email Fetcher", "role": "fetch emails from Gmail", "tools": ["read_emails"]}, ...]
    """
    available_tools = [t["function"]["name"] for t in TOOL_SCHEMAS]

    plan_prompt = f"""You are the Metis Manager. A user wants: "{task}"

Decide what specialized agents to create for this task. Each agent should have:
- name: a short descriptive name (e.g. "API Builder", "Email Fetcher")
- role: what this agent does (one sentence)
- tools: which tools it needs from: {available_tools}

Return ONLY a JSON array. Example:
[{{"name": "Code Writer", "role": "Write the implementation code", "tools": ["file_read", "file_write", "file_edit"]}},
 {{"name": "Tester", "role": "Test the code works", "tools": ["terminal_exec", "file_read"]}}]

Rules:
- Create 1-4 agents (no more)
- Each agent should have a clear, distinct purpose
- Don't create agents for things you can answer directly
- For simple questions, return an empty array []
"""

    resp = chat("default", [{"role": "user", "content": plan_prompt}])
    content = resp.get("content", "")

    # Parse JSON from response
    match = re.search(r'\[.*\]', content, re.DOTALL)
    if match:
        try:
            agents = json.loads(match.group())
            return [a for a in agents if isinstance(a, dict) and "name" in a and "role" in a]
        except json.JSONDecodeError:
            pass
    return []


def _decide_roles(task: str) -> list[str]:
    """Legacy heuristic to decide which agent roles are needed (kept for backward compat)."""
    lower = task.lower()
    roles = []

    if any(w in lower for w in ["build", "create", "implement", "design", "make", "add"]):
        roles.append("planner")
    if any(w in lower for w in ["code", "write", "build", "implement", "create", "function", "class", "api", "fix"]):
        roles.append("coder")
    if any(w in lower for w in ["debug", "fix", "error", "bug", "crash", "broken"]):
        roles.append("debugger")
    if any(w in lower for w in ["test", "verify", "check", "validate", "benchmark"]):
        roles.append("tester")
    if any(w in lower for w in ["research", "find", "search", "look up", "what is", "how to", "explain"]):
        roles.append("researcher")
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

    Uses _plan_agents to dynamically create custom agents via the Manager LLM.
    Yields SSE events. Returns final summary dict.
    """
    if sandbox_roots is None:
        sandbox_roots = [project_dir] if project_dir else ["."]

    # Ask the Manager LLM to plan agents dynamically
    agent_specs = _plan_agents(task)

    # Extract agent names for the task_start event
    agent_names = [a["name"] for a in agent_specs] if agent_specs else []

    thread = AgentThread()

    yield {"type": "task_start", "task": task[:100], "roles": agent_names, "job_id": job_id}

    # Update job status if applicable
    if job_id:
        try:
            from memory import update_job_status
            update_job_status(job_id, "running")
        except Exception:
            pass

    agents_used = []
    all_outputs = {}

    for spec in agent_specs:
        agent_gen = _run_agent(spec, task, thread, sandbox_roots, project_dir)
        output = ""
        # Consume generator, forwarding events
        try:
            while True:
                ev = next(agent_gen)
                yield ev
        except StopIteration as e:
            output = e.value or ""

        agents_used.append(spec["name"])
        all_outputs[spec["name"]] = output

    # Synthesize summary
    summary_parts = []
    for name, output in all_outputs.items():
        summary_parts.append(f"**{name}:** {output[:300]}")
    summary = "\n\n".join(summary_parts)

    # Update job status: clean up one-time tasks, reset recurring ones
    if job_id:
        try:
            from memory import update_job_status, list_jobs, delete_job
            jobs = list_jobs()
            job = next((j for j in jobs if j.get("id") == job_id), None)
            if job and job.get("schedule"):
                # Recurring job — keep alive, reset to pending
                update_job_status(job_id, "pending")
            else:
                # One-time task — clean up
                delete_job(job_id)
        except Exception:
            pass

    yield {"type": "task_complete", "summary": summary[:1000], "agents_used": agents_used, "job_id": job_id}

    return {"summary": summary, "agents_used": agents_used, "thread": thread.messages}
