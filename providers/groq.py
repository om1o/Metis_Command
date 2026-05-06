"""
Groq provider — FREE OpenAI-compatible inference via Groq LPU hardware.

Reads GROQ_API_KEY / GROQ_BASE / GROQ_MODEL from the environment.  Uses the
same OpenAI Chat Completions schema as the GLM provider, so it slots into
brain_engine's cloud-routing logic seamlessly.

Public surface:
    is_configured()                  -> bool
    chat(messages, model, ...)       -> str
    stream_chat(messages, model, ...) -> Generator[dict]  (Metis event dict)

Metis event shape (matches brain_engine.stream_chat):
    {"type": "token",     "delta": str}
    {"type": "reasoning", "delta": str}
    {"type": "done",      "duration_ms": int, "tokens": int}

Free tier limits (as of 2026):
    - 30 requests/minute, 6000 tokens/minute, 1000 requests/day
    - No credit card required
    - Sign up: https://console.groq.com
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Generator, Iterable

import requests


_DEFAULT_BASE = "https://api.groq.com/openai/v1"
_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_THINK_OPEN = re.compile(r"<think>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</think>", re.IGNORECASE)


def api_key() -> str:
    return os.getenv("GROQ_API_KEY", "").strip()


def base_url() -> str:
    return (os.getenv("GROQ_BASE") or _DEFAULT_BASE).rstrip("/")


def default_model() -> str:
    return os.getenv("GROQ_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def is_configured() -> bool:
    """True when the Groq endpoint is usable (API key present)."""
    return bool(api_key())


def is_groq_model(name: str | None) -> bool:
    if not name:
        return False
    n = name.lower()
    return n.startswith("groq/") or n in (
        # General-purpose chat
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "gemma2-9b-it",
        "mixtral-8x7b-32768",
        "llama-3.3-70b-specdec",
        # Newer free-tier models the operator has access to
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3-32b",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        # Speech (Whisper for STT, PlayAI/Orpheus for TTS)
        "whisper-large-v3",
        "whisper-large-v3-turbo",
        "playai-tts",
        # Safety / moderation
        "openai/gpt-oss-20b-safety",
    )


# Recommended model picks per task — feel free to override per-call.
GROQ_RECOMMENDED: dict[str, str] = {
    "reasoning":   "openai/gpt-oss-120b",
    "tools":       "openai/gpt-oss-120b",
    "fast_chat":   "llama-3.3-70b-versatile",
    "vision":      "meta-llama/llama-4-scout-17b-16e-instruct",
    "stt":         "whisper-large-v3-turbo",
    "tts":         "playai-tts",
    "moderation":  "openai/gpt-oss-20b",
}


# ── Non-streaming ────────────────────────────────────────────────────────────

def chat(
    messages: list[dict],
    model: str | None = None,
    *,
    temperature: float = 0.7,
    timeout: float = 120.0,
) -> str:
    """Send `messages` to Groq and return the full reply string."""
    key = api_key()
    if not key:
        return "[Groq] Missing GROQ_API_KEY. Set it in .env or switch to local."
    payload = {
        "model": model or default_model(),
        "messages": messages,
        "stream": False,
        "temperature": temperature,
    }
    try:
        r = requests.post(
            f"{base_url()}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message") or {}).get("content", "") or ""
    except requests.exceptions.ConnectionError as e:
        return f"[Groq] Connection error: {e}"
    except Exception as e:
        return f"[Groq] Error: {e}"


# ── Streaming ────────────────────────────────────────────────────────────────

def stream_chat(
    messages: list[dict],
    model: str | None = None,
    *,
    temperature: float = 0.7,
    cancel=None,
) -> Generator[dict, None, None]:
    """Yield Metis-shaped events from a streaming Groq response."""
    key = api_key()
    if not key:
        yield {"type": "token", "delta": "[Groq] Missing GROQ_API_KEY."}
        yield {"type": "done", "duration_ms": 0, "tokens": 0}
        return

    payload = {
        "model": model or default_model(),
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }
    started = time.time()
    tokens = 0
    inside_think = False
    buffer = ""

    try:
        with requests.post(
            f"{base_url()}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            stream=True,
            timeout=None,
        ) as r:
            r.raise_for_status()
            for raw in r.iter_lines():
                if cancel is not None and getattr(cancel, "cancelled", False):
                    break
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line or line == "[DONE]":
                    if line == "[DONE]":
                        break
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or choices[0].get("message") or {}
                content_delta = delta.get("content") or ""

                if content_delta:
                    tokens += 1
                    buffer += content_delta
                    while True:
                        if inside_think:
                            m = _THINK_CLOSE.search(buffer)
                            if not m:
                                if buffer:
                                    yield {"type": "reasoning", "delta": buffer}
                                    buffer = ""
                                break
                            head, buffer = buffer[: m.start()], buffer[m.end():]
                            if head:
                                yield {"type": "reasoning", "delta": head}
                            inside_think = False
                        else:
                            m = _THINK_OPEN.search(buffer)
                            if not m:
                                if buffer:
                                    yield {"type": "token", "delta": buffer}
                                    buffer = ""
                                break
                            head, buffer = buffer[: m.start()], buffer[m.end():]
                            if head:
                                yield {"type": "token", "delta": head}
                            inside_think = True

                if choices[0].get("finish_reason"):
                    break
    except requests.exceptions.ConnectionError as e:
        yield {"type": "token", "delta": f"[Groq] Connection error: {e}"}
    except Exception as e:
        yield {"type": "token", "delta": f"[Groq] Error: {e}"}

    if buffer:
        yield {"type": "reasoning" if inside_think else "token", "delta": buffer}

    yield {
        "type": "done",
        "duration_ms": int((time.time() - started) * 1000),
        "tokens": tokens,
    }


def stream_to_text(events: Iterable[dict]) -> str:
    return "".join(e["delta"] for e in events if e.get("type") == "token")
