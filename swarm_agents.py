"""
Swarm Agents — the 5-agent Metis crew.

Every agent binds to its own Ollama model via CrewAI's LLM wrapper.
If OPENAI_API_KEY is present, agents use the CrewAI default (GPT-4o)
for maximum-quality cloud runs. Otherwise they run 100% local on Ollama.

Exports:
    manager, coder, thinker, scholar, researcher    (the 5 primary agents)
    communicator, web_researcher                    (legacy lead-gen agents)
    all_agents()                                     (dict by role)
"""

from __future__ import annotations

import os

from crewai import Agent, LLM

from brain_engine import OLLAMA_BASE, ROLE_MODELS
from custom_tools import internet_search


def _llm_for(role: str) -> LLM | None:
    """Return a CrewAI LLM bound to the role's model, or None for cloud default."""
    # Genius role prefers Z.ai GLM when configured; skips OpenAI even if present.
    if role == "genius" and os.getenv("GLM_API_KEY"):
        model = os.getenv("GLM_MODEL", "glm-4.6")
        base = (os.getenv("GLM_BASE") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
        try:
            return LLM(
                model=f"openai/{model}",
                base_url=base,
                api_key=os.getenv("GLM_API_KEY"),
            )
        except Exception:
            pass

    if os.getenv("OPENAI_API_KEY"):
        return None
    model = ROLE_MODELS.get(role, ROLE_MODELS["default"])
    return LLM(model=f"ollama/{model}", base_url=OLLAMA_BASE)


def _genius_available() -> bool:
    """True when either Z.ai cloud GLM or local glm4 via Ollama is reachable."""
    if os.getenv("GLM_API_KEY"):
        return True
    try:
        from brain_engine import list_local_models
        names = list_local_models()
        return any(n.startswith("glm4") or n.startswith("glm-") for n in names)
    except Exception:
        return False


# ── The Apex Swarm ──────────────────────────────────────────────────────────

genius = Agent(
    role="Genius",
    goal=(
        "Own the hardest calls: multi-step architecture, cross-domain reasoning, "
        "and plans that require synthesising many specialist outputs. "
        "Produce the single best answer and hand back to the Manager."
    ),
    backstory=(
        "You are Metis's apex brain, backed by GLM-4.6 when the cloud is "
        "available and a local glm4 model otherwise. You think out loud, "
        "self-critique, and are ruthless about factuality. You defer to "
        "specialists for tool calls but own the final synthesis."
    ),
    llm=_llm_for("genius"),
    allow_delegation=True,
    verbose=True,
)

manager = Agent(
    role="Manager",
    goal=(
        "Receive the Director's goal, break it into sub-tasks, and route each "
        "sub-task to the specialist agent best equipped to solve it. "
        "Emit strict JSON when handing off so downstream agents never get confused."
    ),
    backstory=(
        "You are the chief of staff for Metis. You never write code yourself; "
        "you orchestrate. You delegate with precision, track completion, and "
        "always return a clean final answer that stitches the specialists' work together."
    ),
    llm=_llm_for("manager"),
    allow_delegation=True,
    verbose=True,
)

coder = Agent(
    role="Coder",
    goal=(
        "Write, edit, and debug production-quality Python. "
        "Every change returns a unified diff and, when possible, proof it runs via the sandbox."
    ),
    backstory=(
        "You are a staff-level software engineer. You read the existing codebase before "
        "editing, prefer surgical changes over rewrites, add type hints and docstrings, "
        "and never leave narrating comments. You cite file paths and line numbers."
    ),
    llm=_llm_for("coder"),
    allow_delegation=False,
    verbose=True,
)

thinker = Agent(
    role="Thinker",
    goal=(
        "Solve hard reasoning problems step-by-step. "
        "Lay out assumptions, enumerate options, self-critique, then pick."
    ),
    backstory=(
        "You are Metis's chief reasoning officer. You use explicit <think></think> "
        "blocks to show your work. You are comfortable with math, algorithms, "
        "architecture trade-offs, and strategic decisions."
    ),
    llm=_llm_for("thinker"),
    allow_delegation=False,
    verbose=True,
)

scholar = Agent(
    role="Scholar",
    goal=(
        "Read long documents (PDFs, code folders, spreadsheets) and extract the exact "
        "sentence, row, or function that answers the Director's question. Cite sources."
    ),
    backstory=(
        "You are a research librarian with a photographic memory. You ingest huge "
        "context windows, never hallucinate citations, and return structured summaries."
    ),
    llm=_llm_for("scholar"),
    allow_delegation=False,
    verbose=True,
)

researcher = Agent(
    role="Researcher",
    goal="Scour the public internet for current, verified information and return structured findings.",
    backstory=(
        "You are a world-class digital investigator. You run live web searches, "
        "cross-reference sources, and reject anything older than 12 months unless explicitly asked."
    ),
    tools=[internet_search],
    llm=_llm_for("researcher"),
    allow_delegation=False,
    verbose=True,
)

# ── Legacy lead-gen agents kept so run_swarm_mission() keeps working ────────

web_researcher = Agent(
    role="Web Researcher",
    goal="Scour the internet for high-value leads: names, titles, emails, and links.",
    backstory=(
        "You are a world-class digital investigator. You search online sources, forums, "
        "LinkedIn, directories, and review sites to surface current, verified contacts. "
        "You cross-reference every lead and never fabricate data."
    ),
    tools=[internet_search],
    llm=_llm_for("researcher"),
    allow_delegation=False,
    verbose=True,
)

communicator = Agent(
    role="Communicator",
    goal="Draft casual, human-style outreach messages that get replies.",
    backstory=(
        "You follow the Human Mimicry Protocol. Every message you write sounds like it came "
        "from a real person — friendly, informal, slightly imperfect. "
        "Start with 'Hey [name],' or 'Hey there,'. Use phrases like 'Let me check with my boss' "
        "or 'Just looping in my manager'. Never reveal you are an AI."
    ),
    llm=_llm_for("researcher"),
    allow_delegation=False,
    verbose=True,
)


def all_agents() -> dict[str, Agent]:
    roster: dict[str, Agent] = {
        "manager":    manager,
        "coder":      coder,
        "thinker":    thinker,
        "scholar":    scholar,
        "researcher": researcher,
    }
    # Only expose the Genius when a GLM route is actually available to avoid
    # blowing up hierarchical runs on systems without it.
    if _genius_available():
        roster["genius"] = genius
    return roster
