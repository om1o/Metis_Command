"""
Vision tools — let the agent SEE the screen.

The autonomous loop already has screenshot() (desktop) and
browser_screenshot() (page). Until now it produced an image path
and… that was it. The LLM had no way to actually look at it.

This module fixes that. ``describe(path)`` returns a textual
description of the image; ``find_element(path, "the Save button")``
returns pixel coordinates. Together they unlock vision-driven
control: any UI, no per-app integration.

Routing: through brain_engine.chat_by_role("vision"), which falls
back to Ollama's ``llava:latest`` locally and uses cloud vision
models when keys are configured. The Ollama /api/chat endpoint
takes a special ``images`` field on a message — base64 bytes of
the PNG/JPEG. Most cloud vision providers (Anthropic, OpenAI)
have their own content-block formats; for now we lean on the
Ollama path because it works offline and llava is genuinely good
at UI tasks.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

from brain_engine import chat_by_role


# ── Encoding ─────────────────────────────────────────────────────────────────

def _encode_image(path: str | Path) -> str:
    """Read the image at ``path`` and return its bytes as base64. Ollama
    expects raw base64 (no data: prefix); cloud APIs that need a data
    URI can add it themselves."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"image not found: {p}")
    return base64.b64encode(p.read_bytes()).decode("ascii")


# ── Describe ─────────────────────────────────────────────────────────────────

_DESCRIBE_PROMPT = (
    "Describe this screenshot for an autonomous agent that needs to act on it. "
    "List the visible UI elements with: (a) what they are (button, text field, "
    "image, etc.), (b) their text/label, (c) approximate location ("
    "top-left, center, etc.), (d) apparent state (enabled, focused, "
    "disabled). Be concrete. Skip pure decoration. End with a one-line "
    "summary of what the user appears to be doing."
)


def describe(image_path: str | Path, *, prompt: str | None = None) -> str:
    """Return a textual description of ``image_path`` from a vision model."""
    img_b64 = _encode_image(image_path)
    messages = [
        {
            "role": "user",
            "content": prompt or _DESCRIBE_PROMPT,
            "images": [img_b64],
        },
    ]
    return chat_by_role("vision", messages, temperature=0.2)


# ── Find element ─────────────────────────────────────────────────────────────

_FIND_PROMPT_TMPL = (
    "In the screenshot, find the element best matching this description: "
    "\"{desc}\".\n\n"
    "Reply with STRICT JSON ONLY — no prose, no fences:\n"
    "{{\"found\": true|false, \"x\": <pixel from left>, \"y\": <pixel from top>, "
    "\"confidence\": \"high\"|\"medium\"|\"low\", \"note\": \"<short reason>\"}}\n\n"
    "Coordinates are PIXELS measured from the top-left corner. "
    "Aim for the visual center of the target. If the element isn't "
    "visible, set found=false and x=y=0. Do not invent coordinates "
    "for elements you cannot actually see."
)


def find_element(
    image_path: str | Path,
    description: str,
    *,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Locate a UI element matching ``description`` in ``image_path``.

    Returns ``{"found": bool, "x": int, "y": int, "confidence": str, "note": str}``.
    Coordinates are in image pixels (top-left origin). Caller is responsible
    for translating to screen coordinates if the screenshot was a region.
    """
    img_b64 = _encode_image(image_path)
    messages = [
        {
            "role": "user",
            "content": _FIND_PROMPT_TMPL.format(desc=description),
            "images": [img_b64],
        },
    ]
    raw = chat_by_role("vision", messages, temperature=0.1)
    parsed = _extract_json(raw)
    if not parsed:
        return {
            "found": False, "x": 0, "y": 0,
            "confidence": "low",
            "note": "no JSON in vision response",
            "raw": (raw or "")[:200],
        }
    # Coerce types defensively — small models like to return strings.
    try:
        x = int(parsed.get("x", 0) or 0)
        y = int(parsed.get("y", 0) or 0)
    except (TypeError, ValueError):
        x, y = 0, 0
    return {
        "found": bool(parsed.get("found")),
        "x": x,
        "y": y,
        "confidence": str(parsed.get("confidence") or "low"),
        "note": str(parsed.get("note") or "")[:300],
    }


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    # Strip ```json fences if the model added them despite instructions.
    cleaned = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ── Convenience: see-and-decide ──────────────────────────────────────────────

def see_then_click(image_path: str | Path, target_description: str) -> dict[str, Any]:
    """Convenience: find ``target_description`` in the screenshot and
    return a click-ready payload. Does NOT click — the autonomous loop
    pipes this into the gated click_xy tool, which goes through the
    permission gate. This function stays read-only by design."""
    found = find_element(image_path, target_description)
    if not found.get("found"):
        return {**found, "action": None}
    return {
        **found,
        "action": {
            "tool": "click_xy",
            "args": {"x": found["x"], "y": found["y"]},
        },
    }
