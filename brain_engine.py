"""
Brain Engine — Tri-Core Ollama dispatcher for Metis.

Exposes a role-based API so agents and UI code never hard-code model names:
  - chat_by_role(role, messages)        -> full reply string
  - stream_chat(role, messages, cancel) -> generator of structured events
  - ensure_model(name)                  -> auto-pull from registry
  - get_active_model(role)              -> current model for a role
  - list_local_models()                 -> names present in Ollama

Structured stream events are dicts:
  {"type": "token",     "delta": str}
  {"type": "reasoning", "delta": str}   # <think> blocks from deepseek-r1
  {"type": "done",      "duration_ms": int, "tokens": int}
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Generator, Iterable

import requests

from hardware_scanner import get_hardware_tier

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")
OPENROUTER_BASE = os.getenv("OPENROUTER_BASE", "https://openrouter.ai/api/v1")
OPENROUTER_MANAGER_MODEL = os.getenv("OPENROUTER_MANAGER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")


def _get_api_key():
    """Read the API key lazily so .env has time to load."""
    return os.getenv("OPENROUTER_API_KEY", "")

# ── Role -> model mapping (tuned to the models the user already pulled) ──────
#
# The "genius" role is the top-of-stack brain.  If GLM_API_KEY is set we route
# to Z.ai GLM-4.6 via `providers.glm`; otherwise we fall back to a local glm4
# pulled through Ollama, and finally to qwen2.5-coder:7b if neither exists.
ROLE_MODELS: dict[str, str] = {
    "manager":    OPENROUTER_MANAGER_MODEL,
    "coder":      "qwen2.5-coder:7b",
    "thinker":    "deepseek-r1:1.5b",
    "scholar":    "qwen3.5:4b",
    "researcher": "llama3.2:3b",
    "vision":     "llava:latest",
    "genius":     "glm-4.6",
    "default":    "qwen2.5-coder:7b",
}

# Local fallback models per role (used when a cloud provider is unreachable).
ROLE_LOCAL_FALLBACK: dict[str, str] = {
    "genius": "glm4:9b",
}

# ── Legacy tier mapping kept for backward-compat with older call sites ──────
TIER_MODELS: dict[str, str] = {
    "Lite":      "qwen2.5-coder:1.5b",
    "Pro":       "qwen2.5-coder:7b",
    "Sovereign": "qwen2.5-coder:7b",
}

_THINK_OPEN = re.compile(r"<think>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</think>", re.IGNORECASE)


class CancelToken:
    """Thread-safe cancel flag the UI's Stop button can flip."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


# ── Role resolution ──────────────────────────────────────────────────────────

def get_active_model(role: str = "default") -> str:
    """
    Resolve the active model for a role.

    For `genius`, cascading preference:
        1. GLM cloud (GLM_API_KEY set)
        2. Groq cloud (GROQ_API_KEY set) — FREE tier
        3. Local glm4:9b via Ollama
        4. Local qwen2.5-coder:7b fallback
    """
    if role == "manager" and _get_api_key():
        return OPENROUTER_MANAGER_MODEL
    primary = ROLE_MODELS.get(role, ROLE_MODELS["default"])
    if role == "genius":
        # 1. GLM cloud
        try:
            from providers import glm as _glm
            if _glm.is_configured():
                return _glm.default_model() or primary
        except (ImportError, Exception):
            pass  # OpenRouter is primary; providers module not available
        # 2. Groq cloud (free)
        try:
            from providers import groq as _groq
            if _groq.is_configured():
                return f"groq/{_groq.default_model()}"
        except (ImportError, Exception):
            pass  # OpenRouter is primary; providers module not available
        # 3. Local fallback
        fallback = ROLE_LOCAL_FALLBACK.get(role)
        if fallback:
            try:
                if fallback in list_local_models():
                    return fallback
            except Exception:
                pass
            return fallback
    return primary


def _is_cloud_model(name: str) -> bool:
    """True when the model should be routed to a cloud provider, not Ollama."""
    if name and _get_api_key() and name == OPENROUTER_MANAGER_MODEL:
        return True
    try:
        from providers import glm as _glm
        if _glm.is_glm_model(name):
            return True
    except (ImportError, Exception):
        pass  # OpenRouter is primary; providers module not available
    # Groq models are prefixed with "groq/" or match known Groq model names.
    try:
        from providers import groq as _groq
        if name and name.startswith("groq/"):
            return True
        if _groq.is_groq_model(name):
            return True
    except (ImportError, Exception):
        pass  # OpenRouter is primary; providers module not available
    return False


def list_local_models() -> list[str]:
    try:
        import ollama
        client = ollama.Client(host=OLLAMA_BASE)
        response = client.list()
        models = getattr(response, "models", None)
        if models is None and isinstance(response, dict):
            models = response.get("models", [])
        names: list[str] = []
        for m in models or []:
            if isinstance(m, dict):
                names.append(m.get("model") or m.get("name") or "")
            else:
                # Newer ollama python types use `.model` (not `.name`).
                names.append(getattr(m, "model", None) or getattr(m, "name", None) or "")
        return [n for n in names if n]
    except Exception:
        return []


def ensure_model(name: str, on_progress=None) -> bool:
    """Pull `name` if it isn't already local. Returns True when available."""
    if name in list_local_models():
        return True
    try:
        import ollama
        client = ollama.Client(host=OLLAMA_BASE)
        for progress in client.pull(name, stream=True):
            # Ensure we cast the ProgressResponse back to dict if needed by UI
            # module_manager expects dicts with "status", "total", "completed"
            prog_dict = progress if isinstance(progress, dict) else progress.model_dump()
            if on_progress:
                on_progress(prog_dict)
            if prog_dict.get("status") == "success":
                return True
        return name in list_local_models()
    except Exception as e:
        print(f"[BrainEngine] ensure_model({name}) failed: {e}")
        return False


# ── Non-streaming chat ───────────────────────────────────────────────────────

def chat_by_role(
    role: str,
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.7,
) -> str:
    """Send `messages` to the role's model and return the full reply."""
    model = model or get_active_model(role)

    # Cloud-routed models — try OpenRouter first, then Groq, then GLM.
    if _is_cloud_model(model):
        # Route: OpenRouter (manager)
        if _get_api_key() and model == OPENROUTER_MANAGER_MODEL:
            try:
                from openai import OpenAI
                client = OpenAI(base_url=OPENROUTER_BASE, api_key=_get_api_key())
                resp = client.chat.completions.create(model=model, messages=messages, temperature=temperature)
                reply = resp.choices[0].message.content or ""
                _record_usage(role, model, messages, reply, started=time.time())
                return reply
            except Exception as e:
                model = ROLE_MODELS.get("default", "qwen2.5-coder:7b")
        # Route: Groq (free)
        if model and model.startswith("groq/"):
            try:
                from providers import groq as _groq
                actual_model = model.removeprefix("groq/")
                reply = _groq.chat(messages, model=actual_model, temperature=temperature)
                _record_usage(role, model, messages, reply, started=time.time())
                return reply
            except (ImportError, Exception) as e:
                local_fb = ROLE_LOCAL_FALLBACK.get(role)
                if local_fb:
                    model = local_fb
                else:
                    return f"[BrainEngine] Groq route failed: {e}"
        else:
            # Route: GLM
            try:
                from providers import glm as _glm
                reply = _glm.chat(messages, model=model, temperature=temperature)
                _record_usage(role, model, messages, reply, started=time.time())
                return reply
            except (ImportError, Exception) as e:
                # Fall through to local Ollama with the role's local fallback.
                local_fb = ROLE_LOCAL_FALLBACK.get(role)
                if local_fb:
                    model = local_fb
                else:
                    return f"[BrainEngine] Cloud route failed: {e}"

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    started = time.time()
    try:
        r = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=300)
        r.raise_for_status()
        reply = r.json().get("message", {}).get("content", "")
        _record_usage(role, model, messages, reply, started=started)
        return reply
    except requests.exceptions.ConnectionError:
        return "[BrainEngine] Ollama is not running. Start it with: ollama serve"
    except Exception as e:
        return f"[BrainEngine] Error: {e}"


def _record_usage(role: str, model: str, messages: list[dict], reply: str, *, started: float) -> None:
    """Best-effort hook into usage_tracker so the Wallet can bill cloud calls."""
    try:
        from usage_tracker import estimate_tokens, record
        prompt_text = "\n".join(m.get("content", "") for m in messages)
        record(
            role=role,
            model=model,
            prompt_tokens=estimate_tokens(prompt_text),
            completion_tokens=estimate_tokens(reply or ""),
            duration_ms=int((time.time() - started) * 1000),
        )
    except Exception:
        pass


def chat(messages: list[dict], model: str | None = None, stream: bool = False) -> str:
    """Backward-compat wrapper so older call sites keep working."""
    if stream:
        chunks: list[str] = []
        for ev in stream_chat("default", messages, model=model):
            if ev["type"] == "token":
                chunks.append(ev["delta"])
        return "".join(chunks)
    tier = get_hardware_tier()
    fallback_model = model or TIER_MODELS.get(tier, ROLE_MODELS["default"])
    return chat_by_role("default", messages, model=fallback_model)


def generate(prompt: str, model: str | None = None) -> str:
    return chat([{"role": "user", "content": prompt}], model=model)


# ── Streaming chat with reasoning channel ────────────────────────────────────

def stream_chat(
    role: str,
    messages: list[dict],
    model: str | None = None,
    cancel: CancelToken | None = None,
    temperature: float = 0.7,
) -> Generator[dict, None, None]:
    """
    Stream tokens from Ollama and split deepseek-r1 `<think>...</think>`
    blocks onto a separate `reasoning` channel the UI can hide behind
    a "Show thinking" dropdown.
    """
    model = model or get_active_model(role)

    if _is_cloud_model(model):
        # OpenRouter streaming (manager)
        if _get_api_key() and model == OPENROUTER_MANAGER_MODEL:
            try:
                from openai import OpenAI
                client = OpenAI(base_url=OPENROUTER_BASE, api_key=_get_api_key())
                resp = client.chat.completions.create(model=model, messages=messages, temperature=temperature, stream=True)
                started = time.time()
                for chunk in resp:
                    if cancel and cancel.cancelled:
                        break
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        yield {"type": "token", "delta": delta}
                yield {"type": "done", "duration_ms": int((time.time() - started) * 1000)}
                return
            except Exception as e:
                yield {"type": "token", "delta": f"[OpenRouter error: {e}]"}
                model = ROLE_MODELS.get("default", "qwen2.5-coder:7b")
        # Groq streaming
        if model and model.startswith("groq/"):
            try:
                from providers import groq as _groq
                actual_model = model.removeprefix("groq/")
                for ev in _groq.stream_chat(messages, model=actual_model, temperature=temperature, cancel=cancel):
                    yield ev
                return
            except (ImportError, Exception) as e:
                yield {"type": "token", "delta": f"[BrainEngine] Groq stream failed: {e}"}
                local_fb = ROLE_LOCAL_FALLBACK.get(role)
                if not local_fb:
                    yield {"type": "done", "duration_ms": 0, "tokens": 0}
                    return
                model = local_fb
        else:
            # GLM streaming
            try:
                from providers import glm as _glm
                tokens = 0
                for ev in _glm.stream_chat(messages, model=model, temperature=temperature, cancel=cancel):
                    if ev.get("type") == "done":
                        tokens = int(ev.get("tokens", 0) or 0)
                    yield ev
                return
            except (ImportError, Exception) as e:
                yield {"type": "token", "delta": f"[BrainEngine] Cloud stream failed: {e}"}
                local_fb = ROLE_LOCAL_FALLBACK.get(role)
                if not local_fb:
                    yield {"type": "done", "duration_ms": 0, "tokens": 0}
                    return
                model = local_fb  # fall through to the Ollama path below

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": temperature},
    }
    started = time.time()
    tokens = 0
    inside_think = False
    buffer = ""

    # Read timeout covers "stream wedged mid-response" cases; connect
    # timeout covers Ollama being down.  Either fires -> we raise out.
    # Defaults are tuned for UI responsiveness. Override via env vars if needed.
    stream_connect_timeout = float(os.getenv("METIS_CONNECT_TIMEOUT", "5"))
    stream_read_timeout = float(os.getenv("METIS_STREAM_READ_TIMEOUT", "60"))

    try:
        with requests.post(
            f"{OLLAMA_BASE}/api/chat",
            json=payload,
            stream=True,
            timeout=(stream_connect_timeout, stream_read_timeout),
        ) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if cancel is not None and cancel.cancelled:
                    break
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                chunk = event.get("message", {}).get("content", "")
                if chunk:
                    tokens += 1
                    buffer += chunk
                    # Emit everything up to the next think-boundary.
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

                if event.get("done"):
                    break
    except requests.exceptions.ConnectionError:
        yield {
            "type": "token",
            "delta": "[BrainEngine] Ollama is not running. Start it with: ollama serve",
        }
    except Exception as e:
        yield {"type": "token", "delta": f"[BrainEngine] Error: {e}"}

    # Flush any trailing buffer.
    if buffer:
        ch = "reasoning" if inside_think else "token"
        yield {"type": ch, "delta": buffer}

    yield {
        "type": "done",
        "duration_ms": int((time.time() - started) * 1000),
        "tokens": tokens,
    }


def stream_to_text(events: Iterable[dict]) -> str:
    """Consume a `stream_chat` generator and return only the user-visible text."""
    return "".join(e["delta"] for e in events if e["type"] == "token")
