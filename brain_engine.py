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

import ollama
import requests

from hardware_scanner import get_hardware_tier

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434").rstrip("/")

OLLAMA_TIMEOUT_USER_MESSAGE = (
    "Local AI (Ollama) timed out waiting for a response. "
    "Try a smaller model, a shorter prompt, or raise METIS_OLLAMA_READ_TIMEOUT."
)


class OllamaTransportError(RuntimeError):
    """Catchable wrapper for Ollama HTTP failures (timeouts, connection)."""

    def __init__(self, message: str, *, kind: str = "unknown") -> None:
        super().__init__(message)
        self.kind = kind
        self.user_message = message


def ollama_http_timeouts() -> tuple[float, float]:
    connect = float(os.getenv("METIS_OLLAMA_CONNECT_TIMEOUT", os.getenv("METIS_CONNECT_TIMEOUT", "10")))
    read = float(os.getenv("METIS_OLLAMA_READ_TIMEOUT", os.getenv("METIS_STREAM_READ_TIMEOUT", "300")))
    return (connect, read)


def ollama_reachable(*, connect_s: float | None = None, read_s: float | None = None) -> bool:
    import requests as _req

    dflt_conn, dflt_read = ollama_http_timeouts()
    c = float(connect_s if connect_s is not None else min(dflt_conn, 5.0))
    r = float(read_s if read_s is not None else min(dflt_read, 5.0))
    try:
        resp = _req.get(f"{OLLAMA_BASE}/api/tags", timeout=(c, r))
        return resp.ok
    except Exception:
        return False


def _cloud_routes_allowed() -> bool:
    try:
        from policy_flags import cloud_disabled
        return not cloud_disabled()
    except Exception:
        return True

# ── Role -> model mapping (tuned to the models the user already pulled) ──────
#
# The "genius" role is the top-of-stack brain.  If GLM_API_KEY is set we route
# to Z.ai GLM-4.6 via `providers.glm`; otherwise we fall back to a local glm4
# pulled through Ollama, and finally to qwen2.5-coder:7b if neither exists.
ROLE_MODELS: dict[str, str] = {
    "manager":    "qwen2.5-coder:1.5b",
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
    primary = ROLE_MODELS.get(role, ROLE_MODELS["default"])
    if role == "genius":
        if _cloud_routes_allowed():
            # 1. GLM cloud
            try:
                from providers import glm as _glm
                if _glm.is_configured():
                    return _glm.default_model() or primary
            except Exception:
                pass
            # 2. Groq cloud (free)
            try:
                from providers import groq as _groq
                if _groq.is_configured():
                    return f"groq/{_groq.default_model()}"
            except Exception:
                pass
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
    try:
        from providers import glm as _glm
        if _glm.is_glm_model(name):
            return True
    except Exception:
        pass
    # Groq models are prefixed with "groq/" or match known Groq model names.
    try:
        from providers import groq as _groq
        if name and name.startswith("groq/"):
            return True
        if _groq.is_groq_model(name):
            return True
    except Exception:
        pass
    return False


def list_local_models() -> list[str]:
    connect, read = ollama_http_timeouts()
    try:
        r = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=(connect, read))
        r.raise_for_status()
        data = r.json()
        models = data.get("models") or []
        names: list[str] = []
        for m in models:
            if isinstance(m, dict):
                names.append(m.get("model") or m.get("name") or "")
            else:
                names.append(getattr(m, "model", None) or getattr(m, "name", None) or "")
        return [n for n in names if n]
    except Exception:
        try:
            client = ollama.Client(host=OLLAMA_BASE, timeout=int(max(read, 30)))
            response = client.list()
            models = getattr(response, "models", None)
            if models is None and isinstance(response, dict):
                models = response.get("models", [])
            names = []
            for m in models or []:
                if isinstance(m, dict):
                    names.append(m.get("model") or m.get("name") or "")
                else:
                    names.append(getattr(m, "model", None) or getattr(m, "name", None) or "")
            return [n for n in names if n]
        except Exception:
            return []


def ensure_model(name: str, on_progress=None) -> bool:
    """Pull `name` if it isn't already local. Returns True when available."""
    if name in list_local_models():
        return True
    pull_timeout = int(float(os.getenv("METIS_OLLAMA_PULL_TIMEOUT", str(max(ollama_http_timeouts()[1], 600.0)))))
    try:
        client = ollama.Client(host=OLLAMA_BASE, timeout=pull_timeout)
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

    cloud_ok = _cloud_routes_allowed()
    # Cloud-routed models — try GLM first, then Groq.
    if _is_cloud_model(model) and cloud_ok:
        # Route: Groq (free)
        if model and model.startswith("groq/"):
            try:
                from providers import groq as _groq
                actual_model = model.removeprefix("groq/")
                reply = _groq.chat(messages, model=actual_model, temperature=temperature)
                _record_usage(role, model, messages, reply, started=time.time())
                return reply
            except Exception as e:
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
            except Exception as e:
                # Fall through to local Ollama with the role's local fallback.
                local_fb = ROLE_LOCAL_FALLBACK.get(role)
                if local_fb:
                    model = local_fb
                else:
                    return f"[BrainEngine] Cloud route failed: {e}"

    elif _is_cloud_model(model) and not cloud_ok:
        try:
            from safety import log as _log
            _log("cloud_route_blocked", model=model)
        except Exception:
            pass
        local_fb = ROLE_LOCAL_FALLBACK.get(role) or ROLE_MODELS.get("default")
        model = local_fb

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": -1,
        "options": {"temperature": temperature},
    }
    started = time.time()
    connect_to, read_to = ollama_http_timeouts()
    try:
        r = requests.post(
            f"{OLLAMA_BASE}/api/chat",
            json=payload,
            timeout=(connect_to, read_to),
        )
        r.raise_for_status()
        reply = r.json().get("message", {}).get("content", "")
        _record_usage(role, model, messages, reply, started=started)
        return reply
    except requests.exceptions.Timeout:
        return f"[BrainEngine] {OLLAMA_TIMEOUT_USER_MESSAGE}"
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
            elif ev["type"] == "error":
                return f"[BrainEngine] {ev.get('message', 'error')}"
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

    cloud_ok = _cloud_routes_allowed()
    if _is_cloud_model(model) and cloud_ok:
        # Groq streaming
        if model and model.startswith("groq/"):
            try:
                from providers import groq as _groq
                actual_model = model.removeprefix("groq/")
                for ev in _groq.stream_chat(messages, model=actual_model, temperature=temperature, cancel=cancel):
                    yield ev
                return
            except Exception as e:
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
            except Exception as e:
                yield {"type": "token", "delta": f"[BrainEngine] Cloud stream failed: {e}"}
                local_fb = ROLE_LOCAL_FALLBACK.get(role)
                if not local_fb:
                    yield {"type": "done", "duration_ms": 0, "tokens": 0}
                    return
                model = local_fb  # fall through to the Ollama path below
    elif _is_cloud_model(model) and not cloud_ok:
        try:
            from safety import log as _log
            _log("cloud_route_blocked", model=model)
        except Exception:
            pass
        model = ROLE_LOCAL_FALLBACK.get(role) or ROLE_MODELS["default"]

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "keep_alive": -1,   # keep model permanently in VRAM
        "options": {"temperature": temperature},
    }
    started = time.time()
    tokens = 0
    inside_think = False
    buffer = ""

    stream_connect_timeout, stream_read_timeout = ollama_http_timeouts()

    stream_broken = False
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
    except requests.exceptions.Timeout:
        stream_broken = True
        yield {
            "type": "error",
            "message": OLLAMA_TIMEOUT_USER_MESSAGE,
            "code": "ollama_timeout",
        }
    except requests.exceptions.ConnectionError:
        stream_broken = True
        yield {
            "type": "error",
            "message": "Ollama is not running. Start it with: ollama serve",
            "code": "ollama_unreachable",
        }
    except Exception as e:
        stream_broken = True
        yield {"type": "error", "message": str(e), "code": "ollama_error"}

    # Flush any trailing buffer.
    if not stream_broken and buffer:
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
