"""Central env-driven policy toggles (kill switches)."""

from __future__ import annotations

import os


def _truthy(name: str) -> bool:
    v = os.getenv(name, "").strip().lower()
    return v in ("1", "true", "yes", "on")


def cloud_disabled() -> bool:
    """Block GLM/Groq/OpenAI HTTP routes before external calls."""
    return _truthy("METIS_DISABLE_CLOUD") or _truthy("METIS_CLOUD_DISABLED")


def web_tools_disabled() -> bool:
    """Block web search / internet tools."""
    return _truthy("METIS_DISABLE_WEB_TOOLS")


def autonomous_disabled() -> bool:
    """Block autonomous_loop missions and mission pool submissions."""
    return _truthy("METIS_DISABLE_AUTONOMOUS")
