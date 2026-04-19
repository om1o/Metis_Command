"""
Crew Engine — runs the CrewAI swarm.

Two entry points:
    run_swarm_mission(topic)                  Legacy lead-gen (main.py still uses this).
    run_agentic_mission(user_goal, mode, ...) Modern 5-agent hierarchical mission.

The modern entry point accepts an `on_event` callback so the UI can render
Codex-style tool-call cards in real time as the agents work.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from crewai import Crew, Process

from swarm_agents import all_agents, communicator, web_researcher
from task_manager import create_tasks, build_mission_tasks
from supabase_client import get_client


ToolEvent = dict
OnEvent = Callable[[ToolEvent], None]


# ── Legacy lead-gen flow ─────────────────────────────────────────────────────

def _save_leads_to_supabase(topic: str, results_text: str) -> None:
    try:
        client = get_client()
        client.table("leads").insert({
            "topic": topic,
            "raw_output": results_text,
        }).execute()
        print("[CrewEngine] Results saved to Supabase leads table.")
    except Exception as e:
        print(f"[CrewEngine] Supabase save skipped: {e}")


def run_swarm_mission(target_topic: str, lead_count: int = 10) -> str:
    tasks = create_tasks(web_researcher, communicator, target_topic, lead_count=lead_count)
    crew = Crew(
        agents=[web_researcher, communicator],
        tasks=tasks,
        process=Process.sequential,
        memory=True,
        verbose=True,
    )
    result = crew.kickoff()
    results_text = str(result)
    _save_leads_to_supabase(target_topic, results_text)
    return results_text


# ── Modern agentic mission ──────────────────────────────────────────────────

class _EventBus:
    """Adapts raw CrewAI step callbacks into structured ToolCallEvents."""

    def __init__(self, on_event: OnEvent | None) -> None:
        self.on_event = on_event
        self._started: dict[str, float] = {}

    def emit(self, event: ToolEvent) -> None:
        if self.on_event:
            try:
                self.on_event(event)
            except Exception:
                pass

    def step_callback(self, step: Any) -> None:
        """Receive CrewAI AgentAction / AgentFinish / tool events."""
        now = time.time()
        payload: ToolEvent

        agent = getattr(step, "agent", None) or getattr(step, "role", None) or "agent"
        tool = getattr(step, "tool", None) or getattr(step, "name", None)
        result = getattr(step, "observation", None) or getattr(step, "result", None)
        args = getattr(step, "tool_input", None) or getattr(step, "input", None)

        if tool and args is not None and result is None:
            self._started[str(tool)] = now
            payload = {
                "type": "tool_start",
                "agent": str(agent),
                "tool": str(tool),
                "args": args,
            }
        elif tool and result is not None:
            started = self._started.pop(str(tool), now)
            payload = {
                "type": "tool_end",
                "agent": str(agent),
                "tool": str(tool),
                "args": args,
                "result": str(result)[:4000],
                "duration_ms": int((now - started) * 1000),
            }
        else:
            payload = {
                "type": "thought",
                "agent": str(agent),
                "content": str(step)[:2000],
            }
        self.emit(payload)


def run_agentic_mission(
    user_goal: str,
    mode: str = "chat",
    on_event: OnEvent | None = None,
    session_id: str | None = None,
) -> str:
    """
    Run the 5-agent hierarchical crew.
    `mode` is one of: "chat" | "plan" | "code" | "research".
    `on_event` receives structured tool-call events for the UI.
    """
    agents = all_agents()
    tasks = build_mission_tasks(user_goal, mode=mode, agents=agents)
    bus = _EventBus(on_event)

    bus.emit({"type": "mission_start", "mode": mode, "goal": user_goal})

    # If every task already targets a specific agent we can run sequentially
    # which is faster and avoids CrewAI's manager delegation overhead for
    # simple single-agent modes like "code" / "research" / "plan".
    single_agent = len(tasks) == 1

    crew = Crew(
        agents=list(agents.values()),
        tasks=tasks,
        process=Process.sequential if single_agent else Process.hierarchical,
        manager_llm=None if single_agent else agents["manager"].llm,
        memory=True,
        verbose=True,
        step_callback=bus.step_callback,
    )

    started = time.time()
    try:
        result = crew.kickoff()
        reply = str(result)
    except Exception as e:
        reply = f"[CrewEngine] Mission failed: {e}"
        bus.emit({"type": "error", "message": str(e)})

    bus.emit({
        "type": "mission_end",
        "duration_ms": int((time.time() - started) * 1000),
        "reply_preview": reply[:300],
    })
    return reply
