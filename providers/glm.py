"""
GLM provider — Zhipu AI / Z.ai OpenAI-compatible chat endpoint.

Reads GLM_API_KEY / GLM_BASE / GLM_MODEL from the environment.  Shape mirrors
the OpenAI Chat Completions schema so we can talk to either
`https://open.bigmodel.cn/api/paas/v4` or `https://api.z.ai/api/paas/v4`.

Public surface:
    is_configured()                 -> bool
    chat(messages, model, ...)       -> str
    stream_chat(messages, model, ...) -> Generator[dict]  (Metis event dict)

Metis event shape (matches brain_engine.stream_chat):
    {"type": "token",     "delta": str}
    {"type": "reasoning", "delta": str}
    {"type": "done",      "duration_ms": int, "tokens": int}
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Generator, Iterable

import requests


_DEFAULT_BASE = "https://open.bigmodel.cn/api/paas/v4"
_THINK_OPEN = re.compile(r"<think>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</think>", re.IGNORECASE)


def api_key() -> str:
    return os.getenv("GLM_API_KEY", "").strip()


def base_url() -> str:
    return (os.getenv("GLM_BASE") or _DEFAULT_BASE).rstrip("/")


def default_model() -> str:
    return os.getenv("GLM_MODEL", "glm-4.6").strip() or "glm-4.6"


def is_configured() -> bool:
    """True when the cloud GLM endpoint is usable (API key present)."""
    return bool(api_key())


def is_glm_model(name: str | None) -> bool:
    if not name:
        return False
    n = name.lower()
    return n.startswith("glm-") or n.startswith("zai-") or n.startswith("chatglm")


# ── Non-streaming ────────────────────────────────────────────────────────────

def chat(
    messages: list[dict],
    model: str | None = None,
    *,
    temperature: float = 0.7,
    timeout: float = 300.0,
) -> str:
    """Send `messages` to Z.ai GLM and return the full reply string."""
    key = api_key()
    if not key:
        return "[GLM] Missing GLM_API_KEY. Set it in .env or switch to local."
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
        return f"[GLM] Connection error: {e}"
    except Exception as e:
        return f"[GLM] Error: {e}"


# ── Streaming ────────────────────────────────────────────────────────────────

def stream_chat(
    messages: list[dict],
    model: str | None = None,
    *,
    temperature: float = 0.7,
    cancel=None,
) -> Generator[dict, None, None]:
    """Yield Metis-shaped events from a streaming GLM response."""
    key = api_key()
    if not key:
        yield {"type": "token", "delta": "[GLM] Missing GLM_API_KEY."}
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
                reasoning_delta = delta.get("reasoning_content") or ""
                content_delta = delta.get("content") or ""

                if reasoning_delta:
                    tokens += 1
                    yield {"type": "reasoning", "delta": reasoning_delta}

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
        yield {"type": "token", "delta": f"[GLM] Connection error: {e}"}
    except Exception as e:
        yield {"type": "token", "delta": f"[GLM] Error: {e}"}

    if buffer:
        yield {"type": "reasoning" if inside_think else "token", "delta": buffer}

    yield {
        "type": "done",
        "duration_ms": int((time.time() - started) * 1000),
        "tokens": tokens,
    }


def stream_to_text(events: Iterable[dict]) -> str:
    return "".join(e["delta"] for e in events if e.get("type") == "token")
