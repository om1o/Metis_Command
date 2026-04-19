"""
Task Manager — builds CrewAI task lists for the 5-agent swarm.

Two public surfaces:
    create_tasks(researcher_agent, communicator_agent, target_topic, lead_count=10)
        Legacy lead-gen flow kept for main.py / run_swarm_mission().

    build_mission_tasks(user_goal, mode="chat", agents=None)
        Modern agentic flow. `mode` is one of: "chat" | "plan" | "code" | "research".
"""

from __future__ import annotations

from crewai import Task

from custom_tools import internet_search


# ── Legacy lead-gen task builder ─────────────────────────────────────────────

def create_tasks(
    researcher_agent,
    communicator_agent,
    target_topic: str,
    lead_count: int = 10,
):
    research_task = Task(
        description=(
            f"Find {lead_count} high-value leads related to: '{target_topic}'.\n"
            "For each lead provide:\n"
            "  - Full name\n"
            "  - Title / role\n"
            "  - Company (if applicable)\n"
            "  - Contact info or profile URL\n"
            "  - One-line reason they are a strong target\n\n"
            "Use the internet_search tool. Verify each lead is current (active in the last 12 months). "
            "Do NOT fabricate contacts. If fewer than {lead_count} verified leads exist, return what you find."
        ),
        agent=researcher_agent,
        tools=[internet_search],
        expected_output=(
            f"A numbered list of up to {lead_count} verified leads, each with: "
            "name, title, company, contact/URL, and reason for targeting."
        ),
    )

    outreach_task = Task(
        description=(
            "For every lead in the research results, draft one personalised outreach message.\n\n"
            "Rules:\n"
            "  - Tone: casual, warm, human. Never robotic.\n"
            "  - Open with 'Hey [name],' or 'Hey there,'\n"
            "  - Reference something specific about them (from the research)\n"
            "  - Include one of: 'Let me check with my boss', 'Just looping in my manager', "
            "    or 'We've been keeping an eye on your work'\n"
            "  - Max 5 sentences. No hard sell.\n"
            "  - End with a soft CTA: 'Would love to connect — worth a quick chat?'\n\n"
            "After all drafts, output a SUMMARY TABLE with columns: "
            "Name | Email/URL | Subject Line | First 20 words of message"
        ),
        agent=communicator_agent,
        context=[research_task],
        expected_output=(
            "Individual drafted messages for each lead plus a summary table: "
            "Name | Contact | Subject Line | Message Preview"
        ),
    )

    return [research_task, outreach_task]


# ── Modern agentic mission builder ───────────────────────────────────────────

def build_mission_tasks(
    user_goal: str,
    mode: str = "chat",
    agents: dict | None = None,
) -> list[Task]:
    """
    Return the task list the Manager should orchestrate.
    `agents` must be the dict returned by swarm_agents.all_agents().
    """
    from swarm_agents import all_agents as _all
    agents = agents or _all()
    mode = mode.lower()

    if mode == "code":
        return [
            Task(
                description=(
                    "The Director requested:\n"
                    f"    {user_goal}\n\n"
                    "Write production-quality Python that satisfies the request. "
                    "Return the full file content plus a short explanation of the approach. "
                    "Include type hints and concise docstrings. Never add narrating comments."
                ),
                agent=agents["coder"],
                expected_output="A Python source block plus a 3-5 bullet explanation.",
            ),
        ]

    if mode == "research":
        return [
            Task(
                description=(
                    "Research the following topic and return structured findings with sources:\n"
                    f"    {user_goal}\n\n"
                    "Use the internet_search tool. Reject results older than 12 months unless the "
                    "topic demands history. Cite every claim."
                ),
                agent=agents["researcher"],
                tools=[internet_search],
                expected_output="Structured findings with citations: Topic, Key Facts, Sources.",
            ),
        ]

    if mode == "plan":
        return [
            Task(
                description=(
                    "Produce an execution plan for the Director's goal:\n"
                    f"    {user_goal}\n\n"
                    "Include: 1) assumptions, 2) 3-7 numbered steps, 3) risks, "
                    "4) a clear final deliverable. Pose up to 3 clarifying questions "
                    "with 3 multiple-choice options each before starting."
                ),
                agent=agents["thinker"],
                expected_output="A structured plan with steps, risks, and up to 3 clarifying MCQs.",
            ),
        ]

    # default: chat
    return [
        Task(
            description=(
                "Respond to the Director conversationally and helpfully:\n"
                f"    {user_goal}\n\n"
                "Delegate to the Coder, Scholar, or Researcher if deeper work is needed. "
                "Always return a clean, direct final answer."
            ),
            agent=agents["manager"],
            expected_output="A direct, useful reply to the Director.",
        ),
    ]
