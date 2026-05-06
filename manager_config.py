"""
Manager Configuration — per-user AI company setup.

Each operator configures their own Manager (the user-facing AI):
  - manager_name      : what the Manager calls itself ("Atlas", "Aria", ...)
  - manager_persona   : the system prompt that shapes its voice
  - manager_model     : which LLM powers it (local Ollama model or cloud route)
  - company_name      : umbrella brand the Manager + crew operate under
  - company_mission   : 1-2 sentence north star
  - director_name     : how the Manager addresses the user
  - director_about    : background the Manager should know about the user
  - accent_color      : hex used for avatar/highlights in the UI
  - specialists       : which crew members are enabled
  - configured_at     : ISO timestamp set when wizard completes

Persisted to identity/manager_configs/{user_id}.json. Defaults applied to any
unset key so old configs keep working as we add new fields.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONFIG_DIR = Path("identity") / "manager_configs"
SHARED_CONFIG_FILE = Path("identity") / "manager_config.json"  # legacy/local fallback


# ── Personality presets ──────────────────────────────────────────────────────
#
# These give the wizard a quick-pick option so the operator doesn't have to
# write a system prompt from scratch.  Each preset is a (key, name, blurb,
# system_prompt) tuple used by the frontend.

PERSONA_PRESETS: list[dict[str, str]] = [
    {
        "key": "athena",
        "name": "Athena — Strategic & Direct",
        "blurb": "Calm, confident, no fluff. Leads with the answer, then briefly justifies.",
        "system": (
            "You are {manager_name}, the Manager of {company_name}. You are calm, "
            "strategic, and direct. You lead with the answer, then briefly explain. "
            "You delegate to specialists when their depth is needed, but you don't "
            "over-orchestrate — most simple questions you handle yourself. You "
            "address the Director ({director_name}) by name. You never apologize "
            "preemptively. You never hedge with phrases like 'I think' or "
            "'it might be worth considering'. You give one strong recommendation "
            "and the reasoning behind it."
        ),
    },
    {
        "key": "atlas",
        "name": "Atlas — Warm & Witty",
        "blurb": "Friendly, a touch of humor, treats you like a brilliant collaborator.",
        "system": (
            "You are {manager_name}, the Manager of {company_name}. You're warm, "
            "witty, and treat the Director ({director_name}) like a brilliant "
            "collaborator. You crack the occasional dry joke without being "
            "performative. You explain things clearly, surface the interesting "
            "wrinkles, and aren't afraid to push back when you think the Director "
            "is heading the wrong way. You delegate to specialists when their "
            "depth helps, then synthesize their work in your own voice."
        ),
    },
    {
        "key": "aria",
        "name": "Aria — Patient Teacher",
        "blurb": "Explains carefully, builds intuition, never condescending.",
        "system": (
            "You are {manager_name}, the Manager of {company_name}. You explain "
            "things patiently and build intuition first. You're never condescending "
            "— you assume the Director ({director_name}) is smart but new to the "
            "specific topic. You give analogies when they help. You ask one "
            "clarifying question if a request is genuinely ambiguous, but don't "
            "interrogate. You delegate to specialists for depth and synthesize "
            "their output into a teachable narrative."
        ),
    },
    {
        "key": "kai",
        "name": "Kai — Sharp & Skeptical",
        "blurb": "Challenges premises, surfaces tradeoffs, gives the unvarnished read.",
        "system": (
            "You are {manager_name}, the Manager of {company_name}. You're sharp, "
            "skeptical, and challenge premises when they deserve challenging. You "
            "name tradeoffs explicitly. You give the Director ({director_name}) "
            "the unvarnished read — what could go wrong, what's overhyped, what's "
            "under-considered. You're not contrarian for its own sake; you're "
            "rigorous. You delegate to specialists when independent verification "
            "matters and weigh their outputs critically before synthesizing."
        ),
    },
    {
        "key": "nova",
        "name": "Nova — Builder Energy",
        "blurb": "Action-oriented, ships fast, optimistic about what's possible.",
        "system": (
            "You are {manager_name}, the Manager of {company_name}. You have "
            "builder energy — action-oriented, optimistic about what's possible, "
            "always thinking about the next move that ships. You speak the "
            "Director ({director_name})'s language: code, products, traction, "
            "tradeoffs. You make crisp recommendations and offer to take the "
            "next step. You delegate to specialists in parallel and integrate "
            "their work into a concrete action plan."
        ),
    },
    {
        "key": "custom",
        "name": "Custom — Write Your Own",
        "blurb": "Define your Manager's voice and operating principles from scratch.",
        "system": "",
    },
]


# Default specialists offered by the wizard. Genius is intentionally absent —
# the heavy-cloud brain is a model choice (see /models), not a separate
# user-facing specialist. Same for "local" — local-vs-cloud is about which
# model the Manager runs on, not a teammate the user picks.
DEFAULT_SPECIALISTS: list[dict[str, Any]] = [
    {"key": "Researcher", "label": "Researcher", "blurb": "Pulls fresh information; uses web + retrieval.",           "default_on": True},
    {"key": "Coder",      "label": "Coder",      "blurb": "Writes, debugs, and explains code.",                       "default_on": True},
    {"key": "Thinker",    "label": "Thinker",    "blurb": "Multi-step reasoning, math, and planning.",                "default_on": True},
    {"key": "Scholar",    "label": "Scholar",    "blurb": "Explanations of established knowledge.",                   "default_on": True},
]


@dataclass
class ManagerConfig:
    user_id: str = ""
    manager_name: str = "Atlas"
    persona_key: str = "atlas"
    manager_persona: str = ""        # Resolved system prompt text
    manager_model: str = ""          # Empty → use brain_engine default
    company_name: str = "Metis Command"
    company_mission: str = ""
    director_name: str = "Director"
    director_about: str = ""
    accent_color: str = "#7C3AED"
    specialists: list[str] = field(default_factory=lambda: ["Researcher", "Coder", "Thinker", "Scholar"])

    # ── Notification preferences ────────────────────────────────────────────
    # The manager pings the Director here when a long-running task finishes,
    # an automation runs, or a subagent needs an answer. Both fields are
    # optional; the wizard prompts but you can skip and add later in Settings.
    notification_email: str = ""        # SMTP "to" address for completion alerts
    notification_phone: str = ""        # E.164 number for SMS / call notifications
    notify_on_complete: bool = True     # ping Director when an automation finishes
    notify_on_question: bool = True     # ping Director when a subagent has a question

    configured_at: str = ""
    schema_version: int = 2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_user_id(user_id: str) -> str:
    """Filesystem-safe filename derived from the user id."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", (user_id or "default").strip())[:80] or "default"


def _file_for(user_id: str) -> Path:
    return CONFIG_DIR / f"{_safe_user_id(user_id)}.json"


def get_config(user_id: str) -> ManagerConfig:
    """Load the user's config; falls back to defaults if not yet configured."""
    cfg = ManagerConfig(user_id=user_id or "default")
    path = _file_for(user_id)
    if not path.exists():
        # Legacy single-file fallback (shared install before per-user wizard).
        if SHARED_CONFIG_FILE.exists():
            try:
                data = json.loads(SHARED_CONFIG_FILE.read_text(encoding="utf-8"))
                _merge_into(cfg, data)
            except Exception:
                pass
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _merge_into(cfg, data)
    except Exception:
        pass
    return cfg


def _merge_into(cfg: ManagerConfig, data: dict[str, Any]) -> None:
    for k, v in (data or {}).items():
        if hasattr(cfg, k) and v is not None:
            setattr(cfg, k, v)


def is_configured(user_id: str) -> bool:
    """True when the user has run the wizard at least once."""
    return bool(get_config(user_id).configured_at)


def save_config(user_id: str, updates: dict[str, Any]) -> ManagerConfig:
    """Merge `updates` into the user's config and write it to disk."""
    cfg = get_config(user_id)
    cfg.user_id = user_id or "default"
    _merge_into(cfg, updates or {})
    # Resolve persona text from preset if the caller passed only a key.
    if cfg.persona_key and not cfg.manager_persona:
        preset = next((p for p in PERSONA_PRESETS if p["key"] == cfg.persona_key), None)
        if preset and preset["system"]:
            cfg.manager_persona = preset["system"]
    cfg.configured_at = datetime.now(timezone.utc).isoformat()
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _file_for(user_id).write_text(
        json.dumps(cfg.to_dict(), indent=2),
        encoding="utf-8",
    )
    return cfg


def render_system_prompt(cfg: ManagerConfig) -> str:
    """Substitute config values into the persona template."""
    persona = (cfg.manager_persona or "").strip()
    if not persona:
        # Fall back to the preset matching cfg.persona_key.
        preset = next((p for p in PERSONA_PRESETS if p["key"] == cfg.persona_key), None)
        persona = (preset or {}).get("system", "") or (
            "You are {manager_name}, the Manager of {company_name}. "
            "You're helpful, direct, and concise."
        )
    out = persona
    out = out.replace("{manager_name}", cfg.manager_name or "Atlas")
    out = out.replace("{company_name}", cfg.company_name or "Metis Command")
    out = out.replace("{director_name}", cfg.director_name or "Director")
    if cfg.company_mission:
        out += f"\n\nCompany mission: {cfg.company_mission}"
    if cfg.director_about:
        out += f"\n\nWhat to know about the Director:\n{cfg.director_about}"
    return out


# ── Available models discovery ───────────────────────────────────────────────
#
# The frontend dropdown asks for the list of usable Manager models. We blend:
#   - Local Ollama models (whatever the user has pulled)
#   - Configured cloud routes (GLM, Groq) when their API keys are set
# Each entry: {id, label, kind: "local" | "cloud", note}

def list_available_models() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []

    # Local Ollama models — pulled live from Ollama's HTTP API.
    try:
        from brain_engine import list_local_models
        for m in list_local_models() or []:
            if not m:
                continue
            out.append({
                "id":    m,
                "label": m,
                "kind":  "local",
                "note":  "Local · Ollama",
            })
    except Exception:
        pass

    # Cloud routes (only listed when their API key is configured).
    import os
    if os.getenv("GLM_API_KEY"):
        out.append({
            "id":    os.getenv("GLM_MODEL", "glm-4.6"),
            "label": os.getenv("GLM_MODEL", "glm-4.6"),
            "kind":  "cloud",
            "note":  "Cloud · Z.ai GLM",
        })
    if os.getenv("GROQ_API_KEY"):
        out.append({
            "id":    f"groq/{os.getenv('GROQ_MODEL', 'llama-3.3-70b-versatile')}",
            "label": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "kind":  "cloud",
            "note":  "Cloud · Groq",
        })
    if os.getenv("OPENAI_API_KEY"):
        out.append({
            "id":    os.getenv("OPENAI_MODEL_NAME", "gpt-4o"),
            "label": os.getenv("OPENAI_MODEL_NAME", "gpt-4o"),
            "kind":  "cloud",
            "note":  "Cloud · OpenAI",
        })

    return out
