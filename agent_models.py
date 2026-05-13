"""
Agent model selection — picks the best free model per role.

Cascade: OpenRouter free → Ollama local fallback.
"""
from __future__ import annotations

import os
import time

OPENROUTER_BASE = os.getenv("OPENROUTER_BASE", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

ROLE_MODELS: dict[str, str] = {
    "planner":    "arcee-ai/trinity-large-thinking:free",
    "coder":      "qwen/qwen3-coder:free",
    "debugger":   "google/gemma-4-31b-it:free",
    "tester":     "nvidia/nemotron-3-nano-30b-a3b:free",
    "researcher": "nousresearch/hermes-3-llama-3.1-405b:free",
    "default":    "nvidia/nemotron-3-super-120b-a12b:free",
}

OLLAMA_FALLBACK: dict[str, str] = {
    "planner":    "deepseek-r1:1.5b",
    "coder":      "qwen2.5-coder:7b",
    "debugger":   "qwen2.5-coder:7b",
    "tester":     "qwen2.5-coder:7b",
    "researcher": "llama3.2:3b",
    "default":    "qwen2.5-coder:7b",
}


def pick_model(role: str) -> tuple[str, str]:
    """Return (model_name, provider) for a given agent role."""
    if OPENROUTER_API_KEY:
        model = ROLE_MODELS.get(role, ROLE_MODELS["default"])
        return model, "openrouter"
    model = OLLAMA_FALLBACK.get(role, OLLAMA_FALLBACK["default"])
    return model, "ollama"


def chat_openrouter(
    model: str,
    messages: list[dict],
    temperature: float = 0.7,
    tools: list[dict] | None = None,
    max_retries: int = 1,
) -> dict:
    """Call OpenRouter (OpenAI-compatible). Returns the full response dict.

    Retries once on 429 with 5s backoff.
    """
    # Wallet check (skip for :free models — they cost nothing)
    if ":free" not in model:
        try:
            from wallet import can_spend, try_charge
            allowed, reason = can_spend("cloud_api", 1)
            if not allowed:
                return {"content": f"[Budget exceeded: {reason}]", "tool_calls": [], "model": model, "provider": "openrouter"}
            try_charge("cloud_api", 1, memo=f"agent:{model}", subject=model)
        except ImportError:
            pass  # wallet module optional

    from openai import OpenAI

    client = OpenAI(base_url=OPENROUTER_BASE, api_key=OPENROUTER_API_KEY)
    kwargs: dict = dict(model=model, messages=messages, temperature=temperature)
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message
            return {
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in (msg.tool_calls or [])
                ],
                "model": model,
                "provider": "openrouter",
            }
        except Exception as e:
            if "429" in str(e) and attempt < max_retries:
                time.sleep(5)
                continue
            if attempt == max_retries:
                return {"content": f"[OpenRouter error: {e}]", "tool_calls": [], "model": model, "provider": "openrouter"}
    return {"content": "", "tool_calls": [], "model": model, "provider": "openrouter"}


def chat_ollama(
    model: str,
    messages: list[dict],
    temperature: float = 0.7,
) -> dict:
    """Call local Ollama. Returns dict matching chat_openrouter format."""
    import requests

    base = os.getenv("OLLAMA_BASE", "http://localhost:11434")
    try:
        r = requests.post(
            f"{base}/api/chat",
            json={"model": model, "messages": messages, "stream": False, "options": {"temperature": temperature}},
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
        return {
            "content": data.get("message", {}).get("content", ""),
            "tool_calls": [],
            "model": model,
            "provider": "ollama",
        }
    except Exception as e:
        return {"content": f"[Ollama error: {e}]", "tool_calls": [], "model": model, "provider": "ollama"}


def chat(role: str, messages: list[dict], temperature: float = 0.7, tools: list[dict] | None = None) -> dict:
    """Unified chat — picks model by role, routes to provider. Falls back to Ollama on error."""
    model, provider = pick_model(role)
    if provider == "openrouter":
        result = chat_openrouter(model, messages, temperature, tools)
        # Fallback to Ollama if OpenRouter failed
        if result["content"].startswith("[OpenRouter error:"):
            fallback_model = OLLAMA_FALLBACK.get(role, OLLAMA_FALLBACK["default"])
            result = chat_ollama(fallback_model, messages, temperature)
            result["fallback"] = True
        return result
    return chat_ollama(model, messages, temperature)
