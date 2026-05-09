"""
FastAPI bridge — localhost API so external clients (browser extensions,
Raycast plugins, iPhone companion, shell scripts) can talk to Metis.

Ports: defaults to 7331 but respects METIS_API_PORT from .env.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from dotenv import load_dotenv
load_dotenv()

# noqa-block: imports below intentionally come AFTER load_dotenv() so any
# settings read at module load time pick up values from .env.
from pathlib import Path  # noqa: E402

from fastapi import FastAPI, HTTPException, Query, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import Response, StreamingResponse, FileResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from brain_engine import ROLE_MODELS, list_local_models, stream_chat  # noqa: E402
from artifacts import Artifact, list_artifacts, get_artifact, save_artifact, delete_artifact  # noqa: E402
from metis_version import METIS_VERSION  # noqa: E402
from run_contracts import build_run_contract, normalize_mode, normalize_permission  # noqa: E402


import auth_local  # noqa: E402
import auth_engine  # noqa: E402

app = FastAPI(title="Metis API Bridge", version="18.0.0")

# Frontend lives in ./frontend (HTML + static)
_FRONTEND_DIR = Path(__file__).parent / "frontend"

PUBLIC_PATHS = {"/", "/health", "/version", "/status",
                "/docs", "/openapi.json", "/redoc",
                "/webhooks/stripe",
                # Frontend pages + auth (no bearer token required)
                "/login", "/app", "/signup", "/setup", "/splash", "/analytics-ui",
                "/oauth/callback",
                "/auth/signup", "/auth/signin", "/auth/signout",
                "/auth/oauth/start", "/auth/oauth/complete",
                "/auth/me", "/auth/refresh", "/auth/reset_password",
                "/auth/local-token", "/auth/setup-code",
                # Ollama auto-start probes the splash screen calls before login
                "/ollama/status", "/ollama/start",
                # PWA assets must be public — browsers fetch these before auth
                "/manifest.json", "/sw.js", "/logo-test"}

PUBLIC_PREFIXES = ("/static/",)

app.version = METIS_VERSION


def _verify_token(token: str | None) -> bool:
    """Accept either local install token OR a valid Supabase JWT."""
    if not token:
        return False
    if auth_local.verify(token):
        return True
    # Try as Supabase access token
    try:
        from supabase_client import get_client
        client = get_client()
        resp = client.auth.get_user(token)
        return bool(getattr(resp, "user", None))
    except Exception:
        return False


@app.middleware("http")
async def _auth_middleware(request, call_next):
    """Require Authorization: Bearer <token> on every protected route."""
    path = request.url.path
    if (path in PUBLIC_PATHS
            or any(path.startswith(p) for p in PUBLIC_PREFIXES)
            or request.method == "OPTIONS"):
        return await call_next(request)
    authz = request.headers.get("authorization", "")
    token = (
        authz.split(" ", 1)[1].strip()
        if authz.lower().startswith("bearer ")
        else None
    )
    if not _verify_token(token):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            {"error": {"code": "unauthorized",
                       "message": "missing or invalid Metis token"}},
            status_code=401,
        )
    return await call_next(request)


@app.on_event("startup")
def _boot_services() -> None:
    """Install seeded schedules and resume any persistent subagents on boot."""
    try:
        auth_local.get_or_create()
    except Exception as e:
        print(f"[api_bridge] token init skipped: {e}")
    # Auto-start Ollama in the background so the customer never has to.
    # Non-blocking: don't hold up FastAPI boot — the splash screen polls.
    try:
        import threading, ollama_launcher
        threading.Thread(
            target=ollama_launcher.start_if_needed,
            kwargs={"wait": True, "max_wait_s": 30.0},
            name="ollama-autoboot",
            daemon=True,
        ).start()
    except Exception as e:
        print(f"[api_bridge] ollama auto-start skipped: {e}")
    try:
        from scheduler import seed_default_schedules, start_scheduler
        seed_default_schedules()
        start_scheduler()
    except Exception as e:
        print(f"[api_bridge] scheduler boot skipped: {e}")
    try:
        from agent_roster import resume_persistent_from_disk
        resume_persistent_from_disk()
    except Exception as e:
        print(f"[api_bridge] agent resume skipped: {e}")
    try:
        from wallet import install_default_policies
        install_default_policies()
    except Exception as e:
        print(f"[api_bridge] wallet defaults skipped: {e}")
    # Pre-warm the manager model so the first user message is fast.
    # Runs in its own thread so it never blocks the app boot.
    try:
        import threading
        def _warmup_loop():
            """Load model into VRAM and keep it there with periodic pings.

            Ollama default keep_alive is 5 min — anything past that and the model
            is unloaded, causing a 30s+ cold start. We send keep_alive=-1 (forever)
            on the warmup AND on every chat call, plus a heartbeat ping every
            4 minutes to absolutely guarantee the model stays resident.
            """
            try:
                import requests as _req, time as _t
                from manager_config import get_config
                cfg = get_config("local-install")
                model = cfg.manager_model or "qwen2.5-coder:1.5b"
                # Wait up to 30s for Ollama to be ready
                for _ in range(30):
                    try:
                        r = _req.get("http://127.0.0.1:11434/api/tags", timeout=1)
                        if r.ok:
                            break
                    except Exception:
                        pass
                    _t.sleep(1)
                # Initial warm-up: load model into VRAM AND pre-process
                # the Metis system prompt so its KV cache is hot before
                # the first user turn. With a stable system prompt,
                # Ollama caches the prefix and follow-up turns skip
                # ~20s of prompt processing on small local models.
                try:
                    from manager_orchestrator import _METIS_FULL_PROMPT as _sys
                except Exception:
                    _sys = "You are Metis, a private local-first AI assistant."
                _req.post("http://127.0.0.1:11434/api/chat",
                          json={
                              "model": model,
                              "messages": [
                                  {"role": "system", "content": _sys},
                                  {"role": "user", "content": "ready"},
                              ],
                              "stream": False,
                              "keep_alive": -1,
                              "options": {"num_ctx": 4096},
                          },
                          timeout=180)
                print(f"[api_bridge] model + system-prompt warmed up: {model}")
                # Keep-alive ping every 4 min to be doubly sure it stays resident
                while True:
                    _t.sleep(240)
                    try:
                        # Re-fetch in case user switched models
                        cfg = get_config("local-install")
                        active = cfg.manager_model or model
                        _req.post("http://127.0.0.1:11434/api/generate",
                                  json={"model": active, "prompt": "", "stream": False, "keep_alive": -1},
                                  timeout=30)
                    except Exception:
                        pass
            except Exception as _e:
                print(f"[api_bridge] model warm-up skipped: {_e}")
        threading.Thread(target=_warmup_loop, name="model-warmup-loop", daemon=True).start()
    except Exception as e:
        print(f"[api_bridge] model warm-up thread failed: {e}")

def _resolve_cors_origins() -> list[str]:
    """
    Allow operators to override CORS origins via env var.

    METIS_CORS_ORIGINS=https://app.example.com,https://other.com
    """
    raw = os.getenv("METIS_CORS_ORIGINS", "").strip()
    if raw:
        extras = [o.strip() for o in raw.split(",") if o.strip()]
    else:
        extras = []
    defaults = [
        "http://127.0.0.1", "http://127.0.0.1:8501",
        "http://localhost", "http://localhost:8501",
        "http://localhost:3000", "http://127.0.0.1:3000",  # Next.js dev
        "tauri://localhost",                                # Tauri desktop
    ]
    seen: set[str] = set()
    out: list[str] = []
    for origin in [*defaults, *extras]:
        if origin not in seen:
            seen.add(origin)
            out.append(origin)
    return out


app.add_middleware(
    CORSMiddleware,
    allow_origins=_resolve_cors_origins(),
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    role: str = "manager"
    direct: bool = False   # True = skip orchestrator, stream directly to model
    mode: str = "task"     # task | job
    permission: str = "balanced"  # read | balanced | full
    # Per-turn overrides (MVP 8). When set, these win over the saved
    # manager_config for THIS turn only — the user can try a different
    # model / tone without committing to it. Both optional.
    model: str | None = None        # ollama tag or "groq/<id>" / "glm-4.6" / etc.
    temperature: float | None = None


class ForgeRequest(BaseModel):
    goal: str


# ── Health + meta ────────────────────────────────────────────────────────────

@app.get("/")
def root(request: Request) -> Any:
    # Browsers → splash screen which decides where to route next.
    # API clients → JSON metadata.
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return RedirectResponse(url="/splash", status_code=302)
    return {
        "name": "Metis API Bridge",
        "version": METIS_VERSION,
        "roles": list(ROLE_MODELS.keys()),
        "models_local": list_local_models(),
    }


@app.get("/system/health")
def system_health() -> dict:
    """Check every provider Metis can route to. Used by the UI to show
    a connection-health badge so the operator knows whether they're
    on a fast cloud model or stuck on slow local-only.
    """
    import time as _time
    out: dict[str, Any] = {"checked_at": _time.time()}

    # Ollama (local)
    try:
        import requests as _req
        r = _req.get("http://127.0.0.1:11434/api/tags", timeout=2)
        if r.ok:
            out["ollama"] = {"ok": True, "models": len(r.json().get("models", []))}
        else:
            out["ollama"] = {"ok": False, "reason": f"HTTP {r.status_code}"}
    except Exception as e:
        out["ollama"] = {"ok": False, "reason": f"unreachable: {e}"}

    def _probe_cloud(name: str, env_key: str, url: str, model: str) -> dict:
        key = (os.getenv(env_key) or "").strip()
        if not key:
            return {"ok": False, "reason": "no key in .env",
                    "fix": f"Set {env_key}=<your-key> in .env and restart the bridge."}
        try:
            import requests as _req
            r = _req.post(url,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "max_tokens": 1, "stream": False,
                      "messages": [{"role": "user", "content": "hi"}]},
                timeout=8)
            if r.ok:
                return {"ok": True, "model": model}
            try:
                detail = r.json().get("error", {})
                msg = detail.get("message") if isinstance(detail, dict) else str(detail)
            except Exception:
                msg = r.text[:200]
            return {"ok": False, "reason": f"HTTP {r.status_code}: {msg or 'unknown'}"}
        except Exception as e:
            return {"ok": False, "reason": f"unreachable: {e}"}

    out["groq"] = _probe_cloud(
        "groq", "GROQ_API_KEY",
        "https://api.groq.com/openai/v1/chat/completions",
        os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    )
    out["glm"] = _probe_cloud(
        "glm", "GLM_API_KEY",
        "https://api.z.ai/api/paas/v4/chat/completions",
        os.getenv("GLM_MODEL", "glm-4.6"),
    )
    out["openai"] = _probe_cloud(
        "openai", "OPENAI_API_KEY",
        "https://api.openai.com/v1/chat/completions",
        os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini"),
    )

    # Twilio + SMTP — we can't fully probe without sending, but we can
    # confirm credentials are present.
    twilio_set = bool(
        (os.getenv("TWILIO_SID") or "").strip()
        and (os.getenv("TWILIO_TOKEN") or "").strip()
        and (os.getenv("TWILIO_FROM") or "").strip()
    )
    out["twilio"] = {
        "ok": twilio_set,
        "reason": None if twilio_set else "Set TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM in .env.",
        "destination": (os.getenv("METIS_NOTIFY_PHONE") or "").strip() or None,
    }
    smtp_set = bool(
        (os.getenv("EMAIL_USER") or "").strip()
        and (os.getenv("EMAIL_PASS") or "").strip()
    )
    out["smtp"] = {
        "ok": smtp_set,
        "reason": None if smtp_set else "Set EMAIL_USER + EMAIL_PASS in .env (Gmail needs an App Password).",
        "destination": (os.getenv("METIS_NOTIFY_EMAIL") or "").strip() or None,
    }

    # Headline summary: which manager-eligible provider is fastest available?
    if out["groq"]["ok"]:        out["preferred_manager"] = "groq"
    elif out["glm"]["ok"]:       out["preferred_manager"] = "glm"
    elif out["openai"]["ok"]:    out["preferred_manager"] = "openai"
    elif out["ollama"]["ok"]:    out["preferred_manager"] = "ollama"
    else:                         out["preferred_manager"] = None
    return out


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/version")
def version() -> dict:
    """Stable endpoint the launcher + auto-update polls can read."""
    return {"version": METIS_VERSION}


@app.get("/status")
def status() -> dict:
    """
    Live health snapshot.  Every field is best-effort — missing
    dependencies degrade this to False rather than raising, so the UI
    status bar can always render.
    """
    from time import time as _now
    t0 = _now()

    def _safe(fn, default=None):
        try:
            return fn()
        except Exception as e:
            return {"error": str(e)[:120]} if default is None else default

    ollama_models = _safe(list_local_models, default=[])
    wallet_summary = None
    try:
        from wallet import summary as _wallet_summary
        wallet_summary = _wallet_summary()
    except Exception:
        wallet_summary = None

    brain_stats = None
    try:
        import brains as _brains
        active = _brains.active()
        if active is not None:
            brain_stats = _brains.stats(active)
    except Exception:
        brain_stats = None

    pool_stats = None
    try:
        from concurrency import pool as _pool
        pool_stats = _pool.stats()
    except Exception:
        pool_stats = None

    return {
        "ok": True,
        "version": METIS_VERSION,
        "generated_at_ms": int(_now() * 1000),
        "latency_ms": int((_now() - t0) * 1000),
        "ollama": {
            "reachable": bool(ollama_models),
            "model_count": len(ollama_models or []),
        },
        "wallet":  wallet_summary,
        "brain":   brain_stats,
        "mission_pool": pool_stats,
    }


# ── Streaming chat ───────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    """Server-Sent Events stream of assistant tokens.

    Routes:
      - role == "manager" (default for the UI): full orchestration pipeline
        with planning → specialist delegation → synthesis. Emits richer
        events the frontend renders as subagent activity cards.
      - any other role: raw stream from brain_engine.stream_chat (kept for
        API consumers / scripts that want a specific role directly).
    """
    user_id = _user_id_from_request(request)
    run_mode = normalize_mode(req.mode)
    run_permission = normalize_permission(req.permission)
    wire_message = build_run_contract(
        req.message,
        mode=run_mode,
        permission=run_permission,
    )

    def save_run_report(
        *,
        answer: str,
        duration_ms: int | None,
        agents_used: list[str] | None,
        plan: dict[str, Any] | None,
        agent_outputs: list[dict[str, Any]],
    ) -> Artifact | None:
        if not answer.strip():
            return None
        import time as _time
        created_at = _time.time()
        title = (req.message.strip().splitlines()[0] or "Manager run")[:80]
        plan_summary = (plan or {}).get("summary", "")
        lines = [
            f"# Manager Run Report: {title}",
            "",
            f"- Session: `{req.session_id}`",
            f"- Mode: `{run_mode}`",
            f"- Permission: `{run_permission}`",
            f"- Duration: `{duration_ms or 0} ms`",
            f"- Agents used: {', '.join(agents_used or []) or 'manager only'}",
            "",
            "## Request",
            req.message.strip(),
            "",
        ]
        if plan_summary:
            lines.extend(["## Manager Plan", str(plan_summary), ""])
        if agent_outputs:
            lines.append("## Subagent Reports")
            for item in agent_outputs:
                lines.extend([
                    f"### {item.get('agent', 'agent')}",
                    str(item.get("output", "")).strip(),
                    "",
                ])
        lines.extend(["## Manager Answer", answer.strip(), ""])
        return save_artifact(Artifact(
            type="doc",
            title=f"Manager run: {title}",
            language="markdown",
            content="\n".join(lines),
            metadata={
                "kind": "manager_run_report",
                "session_id": req.session_id,
                "mode": run_mode,
                "permission": run_permission,
                "agents_used": agents_used or [],
                "user_id": user_id,
                "created_at": created_at,
            },
            created_at=created_at,
        ))

    def sse() -> Any:
        full_answer = ""
        run_plan: dict[str, Any] | None = None
        agent_outputs: list[dict[str, Any]] = []
        youtube_answer = _youtube_ai_coding_answer(req.message)
        # Instant heartbeat — browser knows we're alive before model loads
        yield f"data: {json.dumps({'type': 'heartbeat', 'message': 'Processing…'})}\n\n"

        # Direct mode: bypass orchestrator entirely — just stream tokens.
        # Used for Fast + Auto tiers where speed matters more than crew routing.
        if youtube_answer:
            full_answer = youtube_answer
            art = save_run_report(
                answer=full_answer,
                duration_ms=0,
                agents_used=["YouTube search"],
                plan={"summary": "Find a YouTube video about AI coding."},
                agent_outputs=[],
            )
            yield f"data: {json.dumps({'type': 'manager_plan', 'summary': 'Find a YouTube video about AI coding.', 'agents': ['YouTube search'], 'self_handle': False})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'delta': full_answer})}\n\n"
            if art:
                yield f"data: {json.dumps({'type': 'run_artifact_saved', 'id': art.id, 'title': art.title})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'duration_ms': 0, 'agents_used': ['YouTube search']})}\n\n"
            try:
                from memory_loop import persist_turn
                persist_turn(req.session_id, req.message, full_answer, user_id=user_id)
            except Exception as e:
                print(f"[api_bridge] persist_turn failed (non-fatal): {e}")
            return

        use_direct = req.direct or req.role not in ("manager",)
        if use_direct:
            try:
                import manager_config as _mc
                cfg_obj = _mc.get_config(user_id)
                # Per-turn override (MVP 8) wins over saved manager_model.
                model_id = req.model or cfg_obj.manager_model or "qwen2.5-coder:1.5b"
                manager_name = cfg_obj.manager_name or "Metis"
                # Emit identity so UI can show manager name
                yield f"data: {json.dumps({'type': 'manager_identity', 'name': manager_name, 'model': model_id})}\n\n"
                import requests as _req
                t0 = __import__('time').time()
                r = _req.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={
                        "model": model_id,
                        "prompt": wire_message,
                        "stream": True,
                        "keep_alive": -1,
                        "options": {
                            "num_ctx": 4096,
                            "temperature": req.temperature if req.temperature is not None else 0.7,
                        },
                    },
                    stream=True,
                    timeout=120,
                )
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        continue
                    token = chunk.get("response", "")
                    if token:
                        full_answer += token
                        yield f"data: {json.dumps({'type': 'token', 'delta': token})}\n\n"
                    if chunk.get("done"):
                        dur_ms = int((__import__('time').time() - t0) * 1000)
                        art = save_run_report(
                            answer=full_answer,
                            duration_ms=dur_ms,
                            agents_used=[],
                            plan=run_plan,
                            agent_outputs=agent_outputs,
                        )
                        if art:
                            yield f"data: {json.dumps({'type': 'run_artifact_saved', 'id': art.id, 'title': art.title})}\n\n"
                        yield f"data: {json.dumps({'type': 'done', 'duration_ms': dur_ms, 'agents_used': []})}\n\n"
                        break
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        elif req.role == "manager":
            # MVP 14: run the orchestrator on a worker thread so the SSE
            # generator can keep yielding events to the browser even
            # while a tool deep inside autonomous_loop is blocked
            # waiting for the user to click Approve / Deny on a
            # permission card. Two queues: the orchestrator's own event
            # generator + the permissions module's emitter, multiplexed
            # into one ev_queue.
            import queue as _queue
            import threading as _threading
            import permissions as _perm
            from manager_orchestrator import orchestrate

            ev_queue: _queue.Queue = _queue.Queue()
            DONE = object()

            # Tier comes from the composer pill. The orchestrator thread
            # registers the session id + tier + emit-callback so any
            # tool gated through permissions.gate() can find it.
            _perm.set_session(
                req.session_id,
                tier=(req.permission if req.permission in ("read", "balanced", "full") else "balanced"),
                emit=lambda ev, q=ev_queue: q.put(ev),
            )

            def _runner():
                try:
                    for ev in orchestrate(
                        wire_message,
                        user_id=user_id,
                        session_id=req.session_id,
                        model_override=req.model,
                        temperature_override=req.temperature,
                    ):
                        ev_queue.put(ev)
                except Exception as e:
                    ev_queue.put({"type": "error", "message": str(e)})
                finally:
                    ev_queue.put(DONE)

            t = _threading.Thread(target=_runner, daemon=True, name=f"orch:{req.session_id[:8]}")
            t.start()

            try:
                while True:
                    try:
                        ev = ev_queue.get(timeout=15)
                    except _queue.Empty:
                        # Idle heartbeat — keeps the SSE connection alive
                        # while a tool is sitting on an approval prompt.
                        yield "data: {\"type\": \"heartbeat\", \"message\": \"awaiting approval\"}\n\n"
                        continue
                    if ev is DONE:
                        break
                    if ev.get("type") == "token":
                        full_answer += ev.get("delta", "")
                    elif ev.get("type") == "manager_plan":
                        run_plan = dict(ev)
                    elif ev.get("type") == "agent_done":
                        agent_outputs.append(dict(ev))
                    elif ev.get("type") == "done":
                        art = save_run_report(
                            answer=full_answer,
                            duration_ms=ev.get("duration_ms"),
                            agents_used=ev.get("agents_used") if isinstance(ev.get("agents_used"), list) else [],
                            plan=run_plan,
                            agent_outputs=agent_outputs,
                        )
                        if art:
                            yield f"data: {json.dumps({'type': 'run_artifact_saved', 'id': art.id, 'title': art.title})}\n\n"
                    yield f"data: {json.dumps(ev)}\n\n"
            finally:
                _perm.clear_session(req.session_id)
        else:
            for ev in stream_chat(
                req.role,
                [{"role": "user", "content": wire_message}],
            ):
                if ev.get("type") == "token":
                    full_answer += ev.get("delta", "")
                elif ev.get("type") == "done":
                    art = save_run_report(
                        answer=full_answer,
                        duration_ms=ev.get("duration_ms"),
                        agents_used=ev.get("agents_used") if isinstance(ev.get("agents_used"), list) else [],
                        plan=run_plan,
                        agent_outputs=agent_outputs,
                    )
                    if art:
                        yield f"data: {json.dumps({'type': 'run_artifact_saved', 'id': art.id, 'title': art.title})}\n\n"
                yield f"data: {json.dumps(ev)}\n\n"

        # Auto-extract relationship blocks the manager emitted at the end.
        # Format: ```relationship\n{json}\n```. We strip the block from the
        # message, save the contact, drop an inbox notification, and emit
        # a `relationship_saved` event the UI shows as a badge.
        if full_answer:
            try:
                import re as _re
                blk = _re.search(r"```\s*relationship\s*\n([\s\S]+?)\n```", full_answer)
                if blk:
                    parsed = None
                    try:
                        parsed = json.loads(blk.group(1).strip())
                    except Exception:
                        parsed = None
                    full_answer = (full_answer[:blk.start()] + full_answer[blk.end():]).strip()
                    if isinstance(parsed, dict) and parsed.get("name"):
                        try:
                            saved = _save_relationship_data(parsed)
                            yield (
                                "data: "
                                + json.dumps({
                                    "type": "relationship_saved",
                                    "id": saved["id"],
                                    "name": saved["name"],
                                })
                                + "\n\n"
                            )
                            try:
                                notification_body = (
                                    f"Added {saved['name']} to your Relationships."
                                    + (f"\n\n{saved['notes']}" if saved.get("notes") else "")
                                )
                                _inbox.append(
                                    title=f"Saved {saved['name']}",
                                    body=notification_body,
                                    source="manager:relationship",
                                    relationship_id=saved["id"],
                                )
                                import notifications as _notifications
                                _notifications.add(
                                    title=f"Saved {saved['name']}",
                                    body=notification_body,
                                    notif_type="agent",
                                    metadata={
                                        "source": "manager:relationship",
                                        "relationship_id": saved["id"],
                                    },
                                )
                            except Exception:
                                pass
                        except Exception as e:
                            print(f"[api_bridge] relationship save failed: {e}")
            except Exception as e:
                print(f"[api_bridge] relationship parse failed (non-fatal): {e}")

        # Persist the exchange so sessions have real messages.
        session_title = ""
        if full_answer:
            try:
                from memory_loop import persist_turn
                persist_turn(
                    req.session_id, req.message, full_answer,
                    user_id=user_id,
                )
            except Exception as e:
                print(f"[api_bridge] persist_turn failed (non-fatal): {e}")

            # Read the auto-generated title for the sidebar update.
            try:
                from memory import list_sessions_with_meta
                for s in list_sessions_with_meta(user_id):
                    if s["id"] == req.session_id and s.get("title"):
                        session_title = s["title"]
                        break
            except Exception:
                pass

        if session_title:
            yield f"data: {json.dumps({'type': 'session_title', 'session_id': req.session_id, 'title': session_title})}\n\n"

        # Fire an in-app notification for background job completions so the
        # user's bell badge lights up even when they navigate away.
        if full_answer and run_mode == "job":
            try:
                title_label = session_title or req.message.strip()[:60] or "Job complete"
                _notifs.add(
                    title=f"Job complete: {title_label}",
                    body="",
                    notif_type="success",
                )
            except Exception:
                pass

        yield "event: close\ndata: {}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


# ── Multi-model comparison (Phase 13) ────────────────────────────────────────

class CompareRequest(BaseModel):
    message: str
    models: list[str] = Field(default_factory=list)
    session_id: str = ""


@app.post("/chat/compare")
async def chat_compare(req: CompareRequest, request: Request) -> dict:
    """Run the same prompt against multiple models in parallel and return all responses.

    Each entry in the returned ``results`` list is:
      {"model": "<model_id>", "content": "<text>", "duration_ms": <int>, "error": null | "<msg>"}

    The caller should POST with ``models`` as a list of Ollama model IDs.
    If ``models`` is empty or omitted, the two top-ranked local models are used.
    """
    import time as _time
    import requests as _req
    import concurrent.futures

    user_id = _user_id_from_request(request)

    # Resolve model list — fall back to the two highest-priority local models
    models = [m.strip() for m in (req.models or []) if m.strip()]
    if not models:
        try:
            local = list_local_models()
            models = [m["id"] for m in local[:2]] if local else []
        except Exception:
            models = []
    if not models:
        raise HTTPException(status_code=400, detail="No models available for comparison")
    # Cap at 4 to avoid overwhelming Ollama
    models = models[:4]

    ollama_base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    timeout_s = float(os.getenv("METIS_COMPARE_TIMEOUT", "90"))

    def _run_one(model_id: str) -> dict:
        t0 = _time.time()
        try:
            payload = {
                "model": model_id,
                "prompt": req.message,
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 1024},
            }
            resp = _req.post(
                f"{ollama_base}/api/generate",
                json=payload,
                timeout=timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("response", "").strip()
            return {
                "model": model_id,
                "content": content,
                "duration_ms": int((_time.time() - t0) * 1000),
                "error": None,
            }
        except Exception as exc:
            return {
                "model": model_id,
                "content": "",
                "duration_ms": int((_time.time() - t0) * 1000),
                "error": str(exc),
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(models)) as pool:
        futures = {pool.submit(_run_one, m): m for m in models}
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # Stable ordering: same as input models list
    order = {m: i for i, m in enumerate(models)}
    results.sort(key=lambda r: order.get(r["model"], 99))

    return {"results": results, "prompt": req.message}


# ── Web search ───────────────────────────────────────────────────────────────

class WebSearchRequest(BaseModel):
    query: str
    limit: int = 5


class YouTubeSearchRequest(BaseModel):
    query: str
    limit: int = 5


def _clean_youtube_text(value: str) -> str:
    import html as _html
    import re as _re

    value = _html.unescape(value or "")
    value = value.replace("\\u0026", "&")
    value = _re.sub(r"<[^>]+>", "", value)
    value = _re.sub(r"\s+", " ", value)
    return value.strip()


def _youtube_search_results(query: str, *, limit: int = 5) -> list[dict]:
    """Search YouTube result HTML and return watch URLs without requiring an API key."""
    import re as _re
    import urllib.parse
    import urllib.request

    q = query.strip()
    if not q:
        return []

    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(q)}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:  # noqa: S310
        body = response.read().decode("utf-8", errors="replace")

    out: list[dict] = []
    seen: set[str] = set()

    for match in _re.finditer(r"\{\\?\"videoRenderer\\?\":\{", body):
        start = match.start()
        snippet = body[start:start + 9000]
        vid_match = _re.search(r'"videoId":"([^"]+)"', snippet)
        if not vid_match:
            continue
        video_id = vid_match.group(1)
        if video_id in seen:
            continue

        title = ""
        title_match = _re.search(r'"title":\{"runs":\[\{"text":"([^"]+)"', snippet)
        if title_match:
            title = _clean_youtube_text(title_match.group(1))
        if not title:
            title_match = _re.search(r'"title":\{"simpleText":"([^"]+)"', snippet)
            title = _clean_youtube_text(title_match.group(1)) if title_match else ""
        if not title:
            continue

        channel = ""
        owner_match = _re.search(r'"ownerText":\{"runs":\[\{"text":"([^"]+)"', snippet)
        if owner_match:
            channel = _clean_youtube_text(owner_match.group(1))

        length = ""
        length_match = _re.search(r'"lengthText":\{"accessibility":\{"accessibilityData":\{"label":"([^"]+)"', snippet)
        if length_match:
            length = _clean_youtube_text(length_match.group(1))

        published = ""
        published_match = _re.search(r'"publishedTimeText":\{"simpleText":"([^"]+)"', snippet)
        if published_match:
            published = _clean_youtube_text(published_match.group(1))

        seen.add(video_id)
        out.append({
            "title": title,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "channel": channel,
            "published": published,
            "length": length,
            "source": "youtube",
        })
        if len(out) >= max(1, min(limit, 10)):
            break

    if out:
        return out

    # Fallback for compact or escaped YouTube HTML shapes.
    for video_id in dict.fromkeys(_re.findall(r'"videoId":"([^"]+)"', body)):
        if video_id in seen:
            continue
        seen.add(video_id)
        out.append({
            "title": f"YouTube video {video_id}",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "channel": "",
            "published": "",
            "length": "",
            "source": "youtube",
        })
        if len(out) >= max(1, min(limit, 10)):
            break
    return out


def _youtube_ai_coding_answer(message: str) -> str | None:
    lower = message.lower()
    if "youtube" not in lower or not any(term in lower for term in ("ai coding", "coding", "code")):
        return None

    query = "AI coding agents Claude Code Cursor Codex tutorial"
    results = _youtube_search_results(query, limit=3)
    search_url = "https://www.youtube.com/results?search_query=" + __import__("urllib.parse").parse.quote(query)
    if not results:
        return (
            "I could not pull YouTube results from the local search path. "
            f"Open this search instead: {search_url}"
        )

    top = results[0]
    lines = [
        "I found a YouTube video for AI coding:",
        "",
        f"**{top['title']}**",
        f"- URL: {top['url']}",
    ]
    if top.get("channel"):
        lines.append(f"- Channel: {top['channel']}")
    if top.get("published"):
        lines.append(f"- Published: {top['published']}")
    if top.get("length"):
        lines.append(f"- Length: {top['length']}")
    lines.extend([
        "- Why it helps Metis: focus on agentic coding workflows, tool use, and coding-assistant patterns you can apply to the manager/sub-agent system.",
        "",
        f"YouTube search page: {search_url}",
    ])
    if len(results) > 1:
        lines.extend(["", "More options:"])
        for item in results[1:]:
            lines.append(f"- {item['title']} — {item['url']}")
    return "\n".join(lines)


@app.post("/search/web")
async def search_web(req: WebSearchRequest) -> dict:
    """
    Free web search using DuckDuckGo Instant Answer API + HTML scrape fallback.
    Returns titles, snippets, and URLs the AI can cite.
    """
    import urllib.parse, urllib.request, re as _re, html as _html

    q = req.query.strip()
    if not q:
        return {"results": [], "query": ""}
    results: list[dict] = []
    # DuckDuckGo HTML lite endpoint — free, no key, simple to scrape
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(q)}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Metis/0.16)"},
        )
        with urllib.request.urlopen(request, timeout=8) as r:
            body = r.read().decode("utf-8", errors="replace")
        # Parse result blocks
        block_re = _re.compile(
            r'<a rel="nofollow" class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
            r'.*?<a class="result__snippet"[^>]*>(.*?)</a>',
            _re.DOTALL,
        )
        for m in block_re.finditer(body):
            href, title_html, snippet_html = m.groups()
            # DDG wraps URLs in /l/?uddg=...
            real_url = href
            if "uddg=" in href:
                try:
                    real_url = urllib.parse.unquote(
                        href.split("uddg=", 1)[1].split("&", 1)[0]
                    )
                except Exception:
                    pass
            title = _html.unescape(_re.sub(r"<[^>]+>", "", title_html)).strip()
            snippet = _html.unescape(_re.sub(r"<[^>]+>", "", snippet_html)).strip()
            results.append({"title": title, "url": real_url, "snippet": snippet})
            if len(results) >= req.limit:
                break
    except Exception as e:
        return {"results": [], "query": q, "error": str(e)}
    return {"results": results, "query": q}


@app.post("/search/youtube")
async def search_youtube(req: YouTubeSearchRequest) -> dict:
    q = req.query.strip()
    if not q:
        return {"results": [], "query": ""}
    try:
        return {"results": _youtube_search_results(q, limit=req.limit), "query": q}
    except Exception as e:
        return {"results": [], "query": q, "error": str(e)}


# ── File analysis (PDF/text → text for AI) ───────────────────────────────────

@app.post("/files/analyze")
async def files_analyze(request: Request) -> dict:
    """
    Accept a file upload, extract text, return so the AI can reason about it.
    Supports: text/*, .csv, .json, .md, application/pdf (best-effort).
    """
    form = await request.form()
    f = form.get("file")
    if not f:
        raise HTTPException(status_code=400, detail="no file")
    raw = await f.read()
    name = getattr(f, "filename", "upload")
    ctype = getattr(f, "content_type", "") or ""
    text = ""
    try:
        if ctype.startswith("text/") or name.lower().endswith((".csv", ".json", ".md", ".txt", ".log")):
            text = raw.decode("utf-8", errors="replace")
        elif ctype == "application/pdf" or name.lower().endswith(".pdf"):
            try:
                from pypdf import PdfReader
                from io import BytesIO
                reader = PdfReader(BytesIO(raw))
                text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
            except Exception as e:
                text = f"[PDF parse failed: {e}]"
        else:
            text = f"[Binary file {name} ({ctype}) — {len(raw)} bytes; cannot extract text]"
    except Exception as e:
        text = f"[Read failed: {e}]"
    return {"name": name, "type": ctype, "size": len(raw), "text": text[:50000]}


# ── Image + Video generation ─────────────────────────────────────────────────

class ImageGenRequest(BaseModel):
    prompt: str
    width: int = 1024
    height: int = 1024
    style: str = ""          # optional style suffix
    seed: int | None = None

class VideoGenRequest(BaseModel):
    prompt: str
    duration: int = 4        # seconds (used as hint for services that support it)

@app.post("/generate/image")
async def generate_image(req: ImageGenRequest) -> dict:
    """
    Generate an image via Pollinations.ai — completely free, no API key needed.
    Returns an image URL the browser can render directly.
    """
    import urllib.parse, random as _rnd
    prompt = req.prompt.strip()
    if req.style:
        prompt = f"{prompt}, {req.style}"
    seed = req.seed if req.seed is not None else _rnd.randint(1, 99999)
    encoded = urllib.parse.quote(prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={req.width}&height={req.height}&seed={seed}&nologo=true&enhance=true"
    )
    return {"url": url, "prompt": req.prompt, "seed": seed, "width": req.width, "height": req.height}


@app.post("/generate/video")
async def generate_video(req: VideoGenRequest) -> dict:
    """
    Generate a video via Pollinations.ai video endpoint (free).
    Falls back to an animated GIF-style preview using multiple image frames.
    """
    import urllib.parse, random as _rnd
    prompt = req.prompt.strip()
    encoded = urllib.parse.quote(prompt)
    seed = _rnd.randint(1, 99999)
    # Primary: Pollinations video endpoint
    video_url = f"https://video.pollinations.ai/prompt/{encoded}?seed={seed}&duration={req.duration}"
    # Fallback frames for animated preview (different seeds = different frames)
    frames = [
        f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=576&seed={seed+i}&nologo=true"
        for i in range(4)
    ]
    return {
        "video_url": video_url,
        "frames": frames,
        "prompt": req.prompt,
        "seed": seed,
    }


# ── Forge a new skill ────────────────────────────────────────────────────────

@app.post("/forge")
def forge(req: ForgeRequest) -> dict:
    from skill_forge import forge_skill
    art = forge_skill(req.goal)
    return art.to_dict()


# ── Artifacts ────────────────────────────────────────────────────────────────

@app.get("/artifacts")
def artifacts(limit: int = 50) -> list[dict]:
    return [a.to_dict() for a in list_artifacts(limit=limit)]


@app.get("/artifacts/{artifact_id}")
def artifact(artifact_id: str) -> dict:
    a = get_artifact(artifact_id)
    if not a:
        raise HTTPException(status_code=404, detail="artifact not found")
    return a.to_dict()


@app.delete("/artifacts/{artifact_id}")
def artifact_delete(artifact_id: str) -> dict:
    if not delete_artifact(artifact_id):
        raise HTTPException(status_code=404, detail="artifact not found")
    return {"ok": True, "id": artifact_id}


# ── Memory search ────────────────────────────────────────────────────────────

@app.get("/memory/search")
def memory_search(q: str = Query(..., min_length=1), k: int = 5) -> list[dict]:
    from memory_vault import MemoryBank
    return MemoryBank().search(q, n_results=k)


# ── Brains ───────────────────────────────────────────────────────────────────

class BrainSwitchRequest(BaseModel):
    slug: str


class BrainRememberRequest(BaseModel):
    text: str
    kind: str = "semantic"
    brain: str | None = None


@app.get("/brains")
def brains_list() -> dict:
    import brains as _brains
    active = _brains.active()
    return {
        "active": active.slug if active else None,
        "brains": [b.to_dict() for b in _brains.list_brains()],
    }


@app.post("/brains/switch")
def brains_switch(req: BrainSwitchRequest) -> dict:
    import brains as _brains
    try:
        _brains.switch(req.slug)
    except KeyError:
        raise HTTPException(status_code=404, detail="brain not found")
    return {"ok": True, "active": req.slug}


@app.post("/brains/remember")
def brains_remember(req: BrainRememberRequest) -> dict:
    import brains as _brains
    entry_id = _brains.remember(req.text, kind=req.kind, brain=req.brain)
    return {"ok": bool(entry_id), "id": entry_id}


@app.get("/brains/recall")
def brains_recall(q: str = Query(..., min_length=1), k: int = 5,
                  brain: str | None = None) -> list[dict]:
    import brains as _brains
    return _brains.recall(q, k=k, brain=brain)


# ── Wallet ───────────────────────────────────────────────────────────────────

class WalletChargeRequest(BaseModel):
    category: str
    cents: int
    memo: str = ""
    subject: str = ""


class WalletTopUpRequest(BaseModel):
    cents: int
    source: str = "api"


@app.get("/wallet")
def wallet_state() -> dict:
    import wallet as _wallet
    return _wallet.summary()


@app.post("/wallet/charge")
def wallet_charge(req: WalletChargeRequest) -> dict:
    import wallet as _wallet
    try:
        entry = _wallet.charge(req.category, req.cents, req.memo, subject=req.subject)
    except _wallet.BudgetExceeded as e:
        raise HTTPException(status_code=402, detail=str(e))
    except _wallet.ConfirmRequired as e:
        raise HTTPException(status_code=428, detail=str(e))
    return entry.to_dict()


@app.post("/wallet/top_up")
def wallet_top_up(req: WalletTopUpRequest) -> dict:
    import wallet as _wallet
    new_balance = _wallet.top_up(req.cents, source=req.source)
    return {"balance_cents": new_balance}


@app.get("/wallet/ledger")
def wallet_ledger(limit: int = 50, category: str | None = None) -> list[dict]:
    import wallet as _wallet
    return _wallet.ledger(limit=limit, category=category)


# ── Agents + bus ─────────────────────────────────────────────────────────────

class AgentMessageRequest(BaseModel):
    from_slug: str = "orchestrator"
    kind: str = "prompt"
    payload: dict = {}
    channel: str | None = None


@app.get("/agents")
def agents_list() -> dict:
    import agent_roster as _roster
    specs = [s.to_dict() for s in _roster.list_roster()]
    live = _roster.list_persistent()
    for s in specs:
        s["persistent"] = s["slug"] in live
    return {"agents": specs, "persistent": live}


@app.post("/agents/{slug}/start")
def agents_start(slug: str) -> dict:
    import agent_roster as _roster
    ok = _roster.spawn_persistent(slug)
    if not ok:
        raise HTTPException(status_code=404, detail="agent not in roster")
    return {"ok": True, "slug": slug}


@app.post("/agents/{slug}/stop")
def agents_stop(slug: str) -> dict:
    import agent_roster as _roster
    return {"ok": _roster.stop_persistent(slug), "slug": slug}


@app.post("/agents/{slug}/message")
def agents_message(slug: str, req: AgentMessageRequest) -> dict:
    import agent_bus as _bus
    msg = _bus.AgentMessage(
        from_slug=req.from_slug,
        to_slug=slug,
        channel=req.channel,
        kind=req.kind,
        payload=req.payload,
    )
    _bus.publish(msg)
    return msg.to_dict()


# ── Module manager ───────────────────────────────────────────────────────────

@app.get("/tiers/plan")
def tier_plan(tier: str) -> dict:
    from module_manager import plan_tier as _plan, TIER_MANIFEST
    try:
        p = _plan(tier)
    except (ValueError, KeyError):
        # Bad tier → return the list of valid tiers as a hint.
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tier '{tier}'. Valid: {sorted(TIER_MANIFEST.keys())}",
        )
    return {
        "tier": p.tier,
        "models": p.models,
        "missing": p.missing,
        "present": p.present,
        "total_gb": p.total_gb,
        "missing_gb": p.missing_gb,
    }


# ── Sessions ─────────────────────────────────────────────────────────────────

@app.get("/sessions")
def sessions_list(request: Request, limit: int = 50) -> list[dict]:
    """List sessions the caller has accessed, with titles + timestamps.

    Returns ``[{id, title, updated_at}, ...]`` (most-recent first).
    Local-install users get full metadata from SQLite; cloud users get
    bare IDs (title may be empty).
    """
    user_id = _user_id_from_request(request)
    from memory import list_sessions_with_meta
    try:
        return list(list_sessions_with_meta(user_id) or [])[:limit]
    except Exception as e:
        print(f"[api_bridge] /sessions degraded: {e}")
        return []


@app.get("/sessions/search")
def sessions_search(
    request: Request,
    q: str = Query("", description="Full-text search query over chat history"),
    session_id: str | None = Query(None, description="Restrict to a single session"),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict]:
    """Full-text search over local chat history (FTS5)."""
    user_id = _user_id_from_request(request)
    if not q.strip():
        return []
    from memory import search_messages
    try:
        return search_messages(q, user_id=user_id, limit=limit, session_id=session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/sessions/{session_id}")
def sessions_load(session_id: str, request: Request, limit: int = 200) -> list[dict]:
    user_id = _user_id_from_request(request)
    from memory import load_session
    try:
        return list(load_session(session_id, limit=limit, user_id=user_id) or [])
    except Exception as e:
        print(f"[api_bridge] /sessions/{{id}} degraded: {e}")
        return []


@app.delete("/sessions/{session_id}")
def sessions_clear(session_id: str, request: Request) -> dict:
    user_id = _user_id_from_request(request)
    from memory import clear_session
    try:
        clear_session(session_id, user_id=user_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"session clear failed: {e}")
    return {"ok": True, "session_id": session_id}


class RenameRequest(BaseModel):
    title: str


@app.post("/sessions/{session_id}/rename")
def sessions_rename(session_id: str, req: RenameRequest, request: Request) -> dict:
    """Rename a session (pencil icon in the sidebar)."""
    user_id = _user_id_from_request(request)
    from memory import rename_session
    try:
        rename_session(session_id, req.title, user_id=user_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"rename failed: {e}")
    return {"ok": True, "session_id": session_id, "title": req.title.strip()[:120]}


@app.get("/sessions/{session_id}/export")
def sessions_export(
    session_id: str,
    request: Request,
    format: str = "md",
) -> Response:
    """Export a conversation as Markdown, JSON, or plain text.

    Query param ``format``: ``md`` (default), ``json``, ``txt``.
    """
    import json as _json
    from datetime import datetime as _dt

    user_id = _user_id_from_request(request)
    from memory import load_session, list_sessions_with_meta

    messages = load_session(session_id, limit=500, user_id=user_id) or []

    # Try to get session title
    title = session_id
    try:
        meta = list_sessions_with_meta(user_id)
        for s in meta:
            if s.get("id") == session_id and s.get("title"):
                title = s["title"]
                break
    except Exception:
        pass

    fmt = (format or "md").lower().strip()

    if fmt == "json":
        payload = {
            "session_id": session_id,
            "title": title,
            "exported_at": _dt.utcnow().isoformat() + "Z",
            "messages": messages,
        }
        return Response(
            content=_json.dumps(payload, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="metis-{session_id[:12]}.json"'},
        )

    if fmt == "txt":
        lines = [f"Conversation: {title}", f"Session: {session_id}", ""]
        for m in messages:
            role = "You" if m.get("role") == "user" else "Manager"
            lines.append(f"{role}: {m.get('content', '')}\n")
        return Response(
            content="\n".join(lines),
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="metis-{session_id[:12]}.txt"'},
        )

    # Default: Markdown
    lines = [f"# {title}", f"", f"*Session: {session_id}*", f"*Exported: {_dt.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*", ""]
    for m in messages:
        role = m.get("role", "assistant")
        role_label = "**You**" if role == "user" else "**Manager**"
        ts = m.get("created_at", "")[:10]
        lines.append(f"### {role_label}{' · ' + ts if ts else ''}")
        lines.append("")
        lines.append(m.get("content", ""))
        lines.append("")
    return Response(
        content="\n".join(lines),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="metis-{session_id[:12]}.md"'},
    )


# ── Schedules ────────────────────────────────────────────────────────────────

class ScheduleAddRequest(BaseModel):
    goal: str
    kind: str = "interval"  # interval | daily | once | cron
    spec: str = "60"
    project_slug: str | None = None
    auto_approve: bool = True
    action: str = ""
    notify: bool = False    # text + email the operator when this fires
    mode: str = "job"
    permission: str = "balanced"


@app.get("/schedules")
def schedules_list() -> list[dict]:
    from scheduler import list_schedules
    return [s.to_dict() for s in list_schedules()]


@app.post("/schedules")
def schedules_add(req: ScheduleAddRequest) -> dict:
    from scheduler import add as _add
    s = _add(
        req.goal,
        kind=req.kind,
        spec=req.spec,
        project_slug=req.project_slug,
        auto_approve=req.auto_approve,
        action=req.action,
        notify=req.notify,
        mode=normalize_mode(req.mode),
        permission=normalize_permission(req.permission),
    )
    return s.to_dict()


@app.delete("/schedules/{schedule_id}")
def schedules_remove(schedule_id: str) -> dict:
    from scheduler import remove as _remove
    return {"ok": _remove(schedule_id), "id": schedule_id}


@app.post("/schedules/{schedule_id}/toggle")
def schedules_toggle(schedule_id: str) -> dict:
    from scheduler import toggle as _toggle
    return {"enabled": _toggle(schedule_id), "id": schedule_id}


@app.post("/schedules/{schedule_id}/run")
def schedules_run_now(schedule_id: str) -> dict:
    from scheduler import run_now as _run_now
    result = _run_now(schedule_id)
    if result is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    return {"ok": result.get("status") != "failed", **result}


@app.get("/missions")
def missions_list(limit: int = 50) -> list[dict]:
    from concurrency import list_missions, load_persisted_history
    live = [m.to_dict() for m in list_missions(limit=limit)]
    persisted = load_persisted_history(limit=limit)
    seen: set[str] = set()
    rows: list[dict] = []
    for row in [*live, *reversed(persisted)]:
        mission_id = str(row.get("id", ""))
        if not mission_id or mission_id in seen:
            continue
        seen.add(mission_id)
        rows.append(row)
    rows.sort(key=lambda r: float(r.get("submitted_at") or 0), reverse=True)
    return rows[:limit]


@app.get("/missions/{mission_id}")
def mission_get(mission_id: str) -> dict:
    from concurrency import get_mission, load_persisted_history
    mission = get_mission(mission_id)
    if mission is not None:
        return mission.to_dict()
    for row in reversed(load_persisted_history(limit=500)):
        if str(row.get("id", "")) == mission_id:
            return row
    raise HTTPException(status_code=404, detail="mission not found")


@app.post("/missions/{mission_id}/cancel")
def mission_cancel(mission_id: str) -> dict:
    from concurrency import cancel_mission
    return {"ok": cancel_mission(mission_id), "id": mission_id}


# ── Marketplace ──────────────────────────────────────────────────────────────

@app.get("/marketplace")
def marketplace_list() -> list[dict]:
    from marketplace import list_plugins
    return list_plugins() or []


class MarketplaceInstallRequest(BaseModel):
    slug: str


@app.post("/marketplace/install")
def marketplace_install(req: MarketplaceInstallRequest) -> dict:
    from marketplace import list_plugins, install_plugin
    plugins = list_plugins() or []
    target = next((p for p in plugins if p.get("slug") == req.slug), None)
    if not target:
        raise HTTPException(status_code=404, detail="plugin not in catalog")
    ok = install_plugin(target)
    return {"ok": bool(ok), "slug": req.slug}


# ── Relationships ────────────────────────────────────────────────────────────

_RELATIONSHIPS_DIR = Path(__file__).parent / "relationships"
_RELATIONSHIPS_DIR.mkdir(exist_ok=True)


@app.get("/relationships")
def relationships_list() -> list[dict]:
    """List all saved relationships/contacts."""
    items = []
    for f in sorted(_RELATIONSHIPS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data.setdefault("id", f.stem)
            items.append(data)
        except Exception:
            continue
    return items


class RelationshipCreate(BaseModel):
    name: str
    role: str = ""
    company: str = ""
    phone: str = ""
    email: str = ""
    notes: str = ""
    tags: list[str] = []


def _save_relationship_data(data: dict) -> dict:
    """Internal helper used by both the POST route and the manager-emitted
    relationship blocks. Normalizes the payload, mints an id, persists.
    """
    import uuid
    rid = uuid.uuid4().hex[:12]
    rec = {
        "id": rid,
        "name": str(data.get("name") or "").strip()[:200],
        "role": str(data.get("role") or "").strip()[:200],
        "company": str(data.get("company") or "").strip()[:200],
        "phone": str(data.get("phone") or "").strip()[:80],
        "email": str(data.get("email") or "").strip()[:200],
        "notes": str(data.get("notes") or "").strip()[:4000],
        "tags": [str(t).strip()[:40] for t in (data.get("tags") or []) if str(t).strip()][:10],
        "created_at": __import__("datetime").datetime.utcnow().isoformat(),
    }
    if not rec["name"]:
        raise ValueError("relationship needs a name")
    (_RELATIONSHIPS_DIR / f"{rid}.json").write_text(
        json.dumps(rec, indent=2), encoding="utf-8"
    )
    return rec


@app.post("/relationships")
def relationship_create(req: RelationshipCreate) -> dict:
    """Save a new relationship/contact."""
    return _save_relationship_data(req.dict())


@app.delete("/relationships/{rid}")
def relationship_delete(rid: str) -> dict:
    """Delete a relationship by ID."""
    fp = _RELATIONSHIPS_DIR / f"{rid}.json"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="relationship not found")
    fp.unlink()
    return {"ok": True, "id": rid}


@app.get("/relationships/{rid}")
def relationship_get(rid: str) -> dict:
    fp = _RELATIONSHIPS_DIR / f"{rid}.json"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="relationship not found")
    return json.loads(fp.read_text(encoding="utf-8"))


# ── Twilio outreach (MVP 13) ─────────────────────────────────────────────
# Send an SMS or place an outbound voice call to a saved relationship.
# Both require Twilio creds in .env (TWILIO_SID/TOKEN/FROM); calls also
# need TWILIO_CALL_TWIML_URL or a per-call twiml_url override. We always
# log the outreach to notifications + the relationship's notes file so
# there's an audit trail of what got sent.

class RelationshipSMSRequest(BaseModel):
    message: str


class RelationshipCallRequest(BaseModel):
    twiml_url: str | None = None


def _append_to_relationship_log(rid: str, line: str) -> None:
    """Append a one-line audit entry to the relationship's outreach log."""
    fp = _RELATIONSHIPS_DIR / f"{rid}.json"
    if not fp.exists():
        return
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        log = list(data.get("outreach_log") or [])
        log.append({
            "ts": __import__("datetime").datetime.utcnow().isoformat(),
            "entry": line,
        })
        # Keep the log bounded so the file doesn't grow unbounded.
        data["outreach_log"] = log[-50:]
        fp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


@app.post("/relationships/{rid}/sms")
def relationship_send_sms(rid: str, req: RelationshipSMSRequest) -> dict:
    fp = _RELATIONSHIPS_DIR / f"{rid}.json"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="relationship not found")
    rec = json.loads(fp.read_text(encoding="utf-8"))
    phone = (rec.get("phone") or "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="relationship has no phone number")
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="message body is empty")

    # Bail out cleanly if Twilio isn't configured (don't pretend to send).
    if not all((os.getenv("TWILIO_SID"), os.getenv("TWILIO_TOKEN"), os.getenv("TWILIO_FROM"))):
        raise HTTPException(
            status_code=400,
            detail="Twilio not configured. Set TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM in .env.",
        )

    try:
        from comms_link import CommsLink
        ok = CommsLink().send_text_message(phone, msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SMS send failed: {e}")
    if not ok:
        raise HTTPException(status_code=500, detail="Twilio refused the request (see api_bridge.log).")

    _append_to_relationship_log(rid, f"SMS sent: {msg[:120]}")
    try:
        _notifs.add(
            title=f"SMS sent to {rec.get('name','contact')}",
            body=msg[:300],
            notif_type="success",
            metadata={"relationship_id": rid},
        )
    except Exception:
        pass
    return {"ok": True, "id": rid, "to": phone}


@app.post("/relationships/{rid}/call")
def relationship_place_call(rid: str, req: RelationshipCallRequest) -> dict:
    fp = _RELATIONSHIPS_DIR / f"{rid}.json"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="relationship not found")
    rec = json.loads(fp.read_text(encoding="utf-8"))
    phone = (rec.get("phone") or "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="relationship has no phone number")
    if not all((os.getenv("TWILIO_SID"), os.getenv("TWILIO_TOKEN"), os.getenv("TWILIO_FROM"))):
        raise HTTPException(
            status_code=400,
            detail="Twilio not configured. Set TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM in .env.",
        )
    twiml = (req.twiml_url or "").strip() or os.getenv("TWILIO_CALL_TWIML_URL", "").strip()
    if not twiml:
        raise HTTPException(
            status_code=400,
            detail="Set TWILIO_CALL_TWIML_URL in .env (or pass twiml_url) — Twilio needs an instructions URL to read on the call.",
        )

    try:
        from comms_link import CommsLink
        ok = CommsLink().place_outbound_call(phone, twiml_url=twiml)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"call failed: {e}")
    if not ok:
        raise HTTPException(status_code=500, detail="Twilio refused the call (see api_bridge.log).")

    _append_to_relationship_log(rid, f"Call placed via {twiml}")
    try:
        _notifs.add(
            title=f"Call placed to {rec.get('name','contact')}",
            body=f"Twilio dialed {phone}.",
            notif_type="success",
            metadata={"relationship_id": rid},
        )
    except Exception:
        pass
    return {"ok": True, "id": rid, "to": phone}


# ── Inbox ────────────────────────────────────────────────────────────────────
# Storage + helpers live in inbox.py so the scheduler / orchestrator can
# append items without importing api_bridge (which would be circular).

import inbox as _inbox


class InboxCreate(BaseModel):
    title: str
    body: str = ""
    source: str = "agent"
    schedule_id: str | None = None
    relationship_id: str | None = None


@app.get("/inbox")
def inbox_list() -> list[dict]:
    return _inbox.load()


@app.post("/inbox")
def inbox_create(req: InboxCreate) -> dict:
    return _inbox.append(
        title=req.title, body=req.body, source=req.source,
        schedule_id=req.schedule_id, relationship_id=req.relationship_id,
    )


@app.post("/inbox/{iid}/read")
def inbox_read(iid: str) -> dict:
    if not _inbox.mark_read(iid):
        raise HTTPException(status_code=404, detail="inbox item not found")
    return {"ok": True, "id": iid}


@app.delete("/inbox/{iid}")
def inbox_delete_one(iid: str) -> dict:
    if not _inbox.remove(iid):
        raise HTTPException(status_code=404, detail="inbox item not found")
    return {"ok": True, "id": iid}


@app.delete("/inbox")
def inbox_clear() -> dict:
    return {"ok": True, "cleared": _inbox.clear()}


# ── Notifications ────────────────────────────────────────────────────────────
# In-app notification bell.  Agents, the scheduler, and the orchestrator
# can POST here; the UI polls GET /notifications for the unread badge.

import notifications as _notifs


class NotificationCreate(BaseModel):
    title: str
    body: str = ""
    type: str = "info"  # info | success | warning | error | agent
    metadata: dict[str, Any] = Field(default_factory=dict)


@app.get("/notifications")
def notifications_list(
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = Query(False),
) -> list[dict]:
    """Return recent notifications, newest first."""
    return _notifs.list_notifications(limit=limit, unread_only=unread_only)


@app.get("/notifications/count")
def notifications_count() -> dict:
    """Return the unread notification count for the bell badge."""
    return {"unread": _notifs.unread_count()}


@app.post("/notifications")
def notifications_create(req: NotificationCreate) -> dict:
    """Post a new notification (agents, scheduler, external tools)."""
    valid_types = {"info", "success", "warning", "error", "agent"}
    notif_type = req.type if req.type in valid_types else "info"
    return _notifs.add(title=req.title, body=req.body, notif_type=notif_type, metadata=req.metadata)  # type: ignore[arg-type]


@app.post("/notifications/{notif_id}/read")
def notifications_mark_read(notif_id: str) -> dict:
    if not _notifs.mark_read(notif_id):
        raise HTTPException(status_code=404, detail="notification not found")
    return {"ok": True, "id": notif_id}


@app.post("/notifications/read-all")
def notifications_read_all() -> dict:
    return {"ok": True, "marked": _notifs.mark_all_read()}


@app.delete("/notifications")
def notifications_clear() -> dict:
    return {"ok": True, "cleared": _notifs.clear()}


@app.delete("/notifications/{notif_id}")
def notifications_delete_one(notif_id: str) -> dict:
    if not _notifs.remove(notif_id):
        raise HTTPException(status_code=404, detail="notification not found")
    return {"ok": True, "id": notif_id}


# ── Permission gate (MVP 14): user-side decision on tool approval ──

class ActionDecisionRequest(BaseModel):
    decision: str  # "approve" | "deny"


@app.post("/actions/{action_id}/decision")
def action_decide(action_id: str, req: ActionDecisionRequest) -> dict:
    """User clicked Approve or Deny on an approval_required card.

    The orchestrator thread is parked on a threading.Event for this
    action_id; we set the decision and fire it.
    """
    import permissions as _perm
    if req.decision not in ("approve", "deny"):
        raise HTTPException(status_code=400, detail="decision must be 'approve' or 'deny'")
    if not _perm.decide(action_id, req.decision):
        raise HTTPException(status_code=404, detail="no pending action with that id (already handled or expired)")
    return {"ok": True, "id": action_id, "decision": req.decision}


# ── Daily briefings ──────────────────────────────────────────────────────────
# The scheduler's `daily_briefing` action writes a markdown file to
# artifacts/daily_plan_YYYY-MM-DD.md every morning. These routes expose
# them to the UI so the user can read past briefings + trigger a fresh
# one on demand.

import re as _re
_BRIEFING_RX = _re.compile(r"^daily_plan_(\d{4}-\d{2}-\d{2})\.md$")


def _briefings_dir() -> Path:
    """Resolve the artifacts dir the same way daily_tasks does."""
    try:
        from daily_tasks import ARTIFACTS_DIR  # noqa
        return ARTIFACTS_DIR
    except Exception:
        return Path(__file__).parent / "artifacts"


@app.get("/briefings")
def briefings_list() -> list[dict]:
    """List daily plan markdown files, newest first."""
    out: list[dict] = []
    bdir = _briefings_dir()
    if not bdir.exists():
        return out
    for p in sorted(bdir.iterdir(), reverse=True):
        m = _BRIEFING_RX.match(p.name)
        if not m:
            continue
        try:
            stat = p.stat()
            preview = p.read_text(encoding="utf-8")[:280]
        except Exception:
            continue
        out.append({
            "date": m.group(1),
            "filename": p.name,
            "size": stat.st_size,
            "modified_at": stat.st_mtime,
            "preview": preview,
        })
        if len(out) >= 60:
            break
    return out


@app.get("/briefings/{date}")
def briefing_get(date: str) -> dict:
    """Return the full markdown body of one daily plan."""
    if not _re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    p = _briefings_dir() / f"daily_plan_{date}.md"
    if not p.exists():
        raise HTTPException(status_code=404, detail="briefing not found")
    return {
        "date": date,
        "filename": p.name,
        "content": p.read_text(encoding="utf-8"),
    }


@app.post("/briefings/run")
def briefing_run_now() -> dict:
    """Generate today's briefing on demand. Synchronous; can take a few
    seconds because it calls every persistent agent + the manager."""
    try:
        from daily_tasks import daily_briefing
        status = daily_briefing()
        return {"ok": True, "status": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"briefing failed: {e}")


# ── Skills ───────────────────────────────────────────────────────────────────

@app.get("/skills")
def skills_list() -> list[dict]:
    from skill_forge import list_skills
    return list_skills()


class SkillInvokeRequest(BaseModel):
    name: str
    kwargs: dict[str, Any] = {}


@app.post("/skills/invoke")
def skills_invoke(req: SkillInvokeRequest) -> dict:
    from skill_forge import invoke
    try:
        result = invoke(req.name, **(req.kwargs or {}))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "result": result}


# ── Usage forecast ───────────────────────────────────────────────────────────

@app.get("/usage/forecast")
def usage_forecast() -> dict:
    """
    Project month-end spend by extrapolating elapsed usage to month length.
    Best-effort: returns zeros if usage_tracker is empty.
    """
    from datetime import datetime, timedelta
    try:
        import usage_tracker as _u
        events = _u.recent(limit=10000) if hasattr(_u, "recent") else []
    except Exception:
        events = []
    now = datetime.now()
    start_of_month = datetime(now.year, now.month, 1)
    days_elapsed = max((now - start_of_month).days + 1, 1)
    if now.month == 12:
        next_month_start = datetime(now.year + 1, 1, 1)
    else:
        next_month_start = datetime(now.year, now.month + 1, 1)
    days_in_month = (next_month_start - start_of_month).days
    spend_so_far_cents = 0
    try:
        for e in events or []:
            cost = e.get("cost_cents") if isinstance(e, dict) else getattr(e, "cost_cents", 0)
            spend_so_far_cents += int(cost or 0)
    except Exception:
        spend_so_far_cents = 0
    if days_elapsed <= 0:
        projected = 0
    else:
        projected = int(spend_so_far_cents * (days_in_month / days_elapsed))
    return {
        "month": now.strftime("%Y-%m"),
        "days_elapsed": days_elapsed,
        "days_in_month": days_in_month,
        "spend_so_far_cents": spend_so_far_cents,
        "projected_month_end_cents": projected,
    }


# ── Analytics ────────────────────────────────────────────────────────────────

@app.get("/analytics")
def analytics_summary(request: Request) -> dict:
    """Aggregate usage stats for the analytics dashboard."""
    from datetime import datetime
    now = datetime.now()

    user_id = _user_id_from_request(request)

    # Sessions
    try:
        from memory import list_sessions_with_meta
        all_sessions = list(list_sessions_with_meta(user_id) or [])
    except Exception:
        all_sessions = []

    # Missions (live + persisted)
    try:
        from concurrency import list_missions as _live_missions, load_persisted_history
        live = [m.to_dict() for m in _live_missions(limit=1000)]
        persisted = load_persisted_history(limit=1000)
        seen: set[str] = set()
        all_missions: list[dict] = []
        for row in [*live, *persisted]:
            mid = str(row.get("id", ""))
            if mid and mid not in seen:
                seen.add(mid)
                all_missions.append(row)
    except Exception:
        all_missions = []

    # Schedules
    try:
        from scheduler import list_schedules
        schedules = list_schedules()
    except Exception:
        schedules = []

    # Wallet
    try:
        import wallet as _w
        w = _w.summary()
        spent_cents = w.get("monthly_spent_cents", 0) if isinstance(w, dict) else 0
        cap_cents = w.get("monthly_cap_cents", 0) if isinstance(w, dict) else 0
    except Exception:
        spent_cents = 0
        cap_cents = 0

    # Token usage
    try:
        import usage_tracker as _u
        usage = _u.summary()
    except Exception:
        usage = {"calls": 0, "total_tokens": 0, "cost_usd": 0.0, "by_model": {}}

    # Inbox
    try:
        from inbox import load as inbox_load
        inbox_items = inbox_load()
        unread = sum(1 for i in inbox_items if not i.get("read", False))
    except Exception:
        inbox_items = []
        unread = 0

    # Mission stats
    status_counts: dict[str, int] = {}
    for m in all_missions:
        s = str(m.get("status", "unknown"))
        status_counts[s] = status_counts.get(s, 0) + 1

    def _updated_at_ms(value: object) -> float:
        if value in (None, ""):
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000
        except Exception:
            return 0.0

    # Recent activity (last 7 days) — sessions updated in that window
    week_ago_ms = (now.timestamp() - 7 * 86400) * 1000
    recent_sessions = sum(
        1 for s in all_sessions
        if _updated_at_ms(s.get("updated_at")) > week_ago_ms
    )

    return {
        "generated_at": now.isoformat(),
        "sessions": {
            "total": len(all_sessions),
            "active_last_7d": recent_sessions,
        },
        "missions": {
            "total": len(all_missions),
            "by_status": status_counts,
            "success": status_counts.get("success", 0),
            "failed": status_counts.get("failed", 0),
        },
        "schedules": {
            "total": len(schedules),
            "active": sum(1 for s in schedules if getattr(s, "enabled", s.get("enabled", False) if isinstance(s, dict) else False)),
        },
        "inbox": {
            "total": len(inbox_items),
            "unread": unread,
        },
        "tokens": {
            "calls": usage.get("calls", 0),
            "total": usage.get("total_tokens", 0),
            "cost_usd": usage.get("cost_usd", 0.0),
            "by_model": usage.get("by_model", {}),
        },
        "wallet": {
            "spent_cents": spent_cents,
            "cap_cents": cap_cents,
        },
    }


# ── Agent health ─────────────────────────────────────────────────────────────

@app.get("/agents/health")
def agents_health() -> list[dict]:
    try:
        from agent_roster import get_agent_health
        return get_agent_health()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"health unavailable: {e}")


# ── Stripe webhook ───────────────────────────────────────────────────────────

@app.post("/webhooks/stripe")
async def stripe_webhook(request) -> dict:  # type: ignore[no-untyped-def]
    """
    Wallet top-up via Stripe Checkout completion.

    This endpoint is on the PUBLIC_PATHS allowlist below — Stripe's webhook
    sender doesn't carry the local Bearer token. Signature verification is
    delegated to wallet.handle_stripe_webhook (uses STRIPE_WEBHOOK_SECRET).
    """
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        from wallet import handle_stripe_webhook
        result = handle_stripe_webhook(body, sig)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"webhook failed: {e}")
    return result


# ── Auth routes ──────────────────────────────────────────────────────────────

class SignUpRequest(BaseModel):
    email: str
    password: str


class SignInRequest(BaseModel):
    email: str
    password: str


class OAuthStartRequest(BaseModel):
    provider: str  # "google" | "github"
    redirect_to: str | None = None


class OAuthCompleteRequest(BaseModel):
    code: str
    state: str | None = None


class ResetPasswordRequest(BaseModel):
    email: str


def _session_payload(session: Any) -> dict:
    if session is None:
        return {}
    
    def _get(obj, attr, default=None):
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    return {
        "access_token": _get(session, "access_token"),
        "refresh_token": _get(session, "refresh_token"),
        "expires_at": _get(session, "expires_at"),
        "token_type": _get(session, "token_type", "bearer"),
    }


def _user_payload(user: Any) -> dict:
    if user is None:
        return {}

    def _get(obj, attr, default=None):
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    return {
        "id": _get(user, "id"),
        "email": _get(user, "email"),
        "created_at": str(_get(user, "created_at", "") or ""),
        "user_metadata": _get(user, "user_metadata", {}) or {},
    }


SETUP_CODE_PREFIX = "metis-local:"


def _is_loopback_request(request: Request) -> bool:
    host = request.headers.get("host", "")
    client_host = getattr(request.client, "host", "")
    loopback = {"127.0.0.1", "localhost", "::1"}
    return any(h in host for h in loopback) or client_host in loopback


def _setup_code_from_token(token: str) -> str:
    return f"{SETUP_CODE_PREFIX}{token}"


def setup_code_to_token(code: str | None) -> str:
    if not code:
        return ""
    normalized = "".join(str(code).strip().strip("\"'").split())
    if normalized.lower().startswith(SETUP_CODE_PREFIX):
        return normalized[len(SETUP_CODE_PREFIX):]
    return normalized


@app.get("/auth/local-token")
def auth_local_token(request: Request) -> dict:
    """
    Bootstrap endpoint — returns the local install bearer token so the
    browser SPA can authenticate without a cloud account.

    SECURITY: Only reachable at 127.0.0.1 (the server binds to localhost
    only). External traffic never reaches this; there is no secret to leak.
    """
    if not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="local-only endpoint")
    token = auth_local.get_or_create()
    return {
        "token": token,
        "setup_code": _setup_code_from_token(token),
        "type": "local-install",
    }


@app.get("/auth/setup-code")
def auth_setup_code(request: Request) -> dict:
    """
    Return a copy-safe local setup code for this install.

    The code wraps the existing local bearer token so users can paste a clearly
    identified setup value without exposing a second credential format.
    """
    if not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="local-only endpoint")
    token = auth_local.get_or_create()
    return {
        "code": _setup_code_from_token(token),
        "type": "local-install",
    }


@app.post("/auth/signup")
def auth_signup(req: SignUpRequest) -> dict:
    try:
        out = auth_engine.sign_up(req.email, req.password)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "user": _user_payload(out.get("user")),
        "session": _session_payload(out.get("session")),
    }


@app.post("/auth/signin")
def auth_signin(req: SignInRequest) -> dict:
    try:
        out = auth_engine.sign_in(req.email, req.password)
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))
    sess = out.get("session")
    if not sess or not getattr(sess, "access_token", None):
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {
        "user": _user_payload(out.get("user")),
        "session": _session_payload(sess),
    }


@app.post("/auth/signout")
def auth_signout() -> dict:
    try:
        auth_engine.sign_out()
    except Exception:
        pass
    return {"ok": True}


@app.get("/auth/me")
def auth_me(request: Request) -> dict:
    """Identify the caller. Accepts either a Supabase JWT or the local-install
    token (used by CLI tools, scripts, and the desktop app on first boot before
    a cloud account is linked)."""
    authz = request.headers.get("authorization", "")
    token = (authz.split(" ", 1)[1].strip()
             if authz.lower().startswith("bearer ") else None)
    if not token:
        raise HTTPException(status_code=401, detail="no token")
    # Local install token → return a synthetic local user so the SPA can boot.
    if auth_local.verify(token):
        return {
            "user": {
                "id": "local-install",
                "email": "operator@local",
                "created_at": "",
                "user_metadata": {"local_install": True},
            }
        }
    # Otherwise try as a Supabase JWT.
    try:
        from supabase_client import get_client
        client = get_client()
        resp = client.auth.get_user(token)
        user = getattr(resp, "user", None)
        if not user:
            raise HTTPException(status_code=401, detail="invalid token")
        return {"user": _user_payload(user)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.post("/auth/oauth/start")
def auth_oauth_start(req: OAuthStartRequest) -> dict:
    if req.provider not in ("google", "github"):
        raise HTTPException(status_code=400, detail="unsupported provider")
    redirect_to = req.redirect_to or f"http://127.0.0.1:{os.getenv('METIS_API_PORT', '7331')}/oauth/callback"
    try:
        url, _verifier = auth_engine.start_oauth(provider=req.provider, redirect_to=redirect_to)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"url": url}


@app.post("/auth/oauth/complete")
def auth_oauth_complete(req: OAuthCompleteRequest) -> dict:
    try:
        out = auth_engine.complete_oauth(code=req.code, state=req.state)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "user": _user_payload(out.get("user")),
        "session": _session_payload(out.get("session")),
    }


@app.post("/auth/reset_password")
def auth_reset_password(req: ResetPasswordRequest) -> dict:
    try:
        auth_engine.reset_password(req.email)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


# ── Frontend (HTML + static) ─────────────────────────────────────────────────

if (_FRONTEND_DIR / "static").exists():
    # No-cache for HTML + JS so browsers always pick up the latest UI.
    # Without this, fetch('/static/js/api.js') returns a stale browser cache
    # and new methods (e.g. generateImage) appear undefined to the page.
    class _NoCacheStaticFiles(StaticFiles):
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            ext = path.lower().rsplit(".", 1)[-1] if "." in path else ""
            if ext in ("js", "css", "html"):
                response.headers["Cache-Control"] = "no-store, must-revalidate"
                response.headers["Pragma"] = "no-cache"
            return response
    app.mount(
        "/static",
        _NoCacheStaticFiles(directory=str(_FRONTEND_DIR / "static")),
        name="static",
    )


@app.get("/login")
def page_login() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "login.html")


@app.get("/signup")
def page_signup() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "signup.html")


@app.get("/app")
def page_app() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "app.html")


@app.get("/oauth/callback")
def oauth_callback() -> FileResponse:
    """Receives ?code= from OAuth provider; the page JS exchanges it."""
    return FileResponse(_FRONTEND_DIR / "oauth_callback.html")


@app.get("/setup")
def page_setup() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "setup.html")


@app.get("/splash")
def page_splash() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "splash.html")


@app.get("/analytics-ui")
def page_analytics() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "analytics.html")


@app.get("/logo-test")
def page_logo_test() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "logo-test.html")


# ── PWA assets (Phase 18) ────────────────────────────────────────────────────

@app.get("/manifest.json")
def pwa_manifest() -> FileResponse:
    """Web App Manifest — enables Add to Home Screen on iOS/Android."""
    fp = _FRONTEND_DIR / "manifest.json"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="manifest.json not found")
    return FileResponse(fp, media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
def pwa_service_worker() -> FileResponse:
    """Service worker served from root scope so it can control all pages."""
    fp = _FRONTEND_DIR / "static" / "sw.js"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="sw.js not found")
    return FileResponse(fp, media_type="application/javascript",
                        headers={"Cache-Control": "no-cache, no-store",
                                 "Service-Worker-Allowed": "/"})


# ── Manager config + models ──────────────────────────────────────────────────

def _user_id_from_request(request: Request) -> str:
    """Best-effort: pull the authenticated user's id from their bearer token."""
    authz = request.headers.get("authorization", "")
    token = (authz.split(" ", 1)[1].strip()
             if authz.lower().startswith("bearer ") else None)
    if not token:
        return "default"
    if auth_local.verify(token):
        return "local-install"
    try:
        from supabase_client import get_client
        resp = get_client().auth.get_user(token)
        u = getattr(resp, "user", None)
        return getattr(u, "id", None) or "default"
    except Exception:
        return "default"


@app.get("/manager/config")
def manager_config_get(request: Request) -> dict:
    import manager_config as _mc
    user_id = _user_id_from_request(request)
    cfg = _mc.get_config(user_id)
    return {
        "config": cfg.to_dict(),
        "is_configured": bool(cfg.configured_at),
        "presets": _mc.PERSONA_PRESETS,
        "specialists": _mc.DEFAULT_SPECIALISTS,
    }


class ManagerConfigUpdate(BaseModel):
    manager_name: str | None = None
    persona_key: str | None = None
    manager_persona: str | None = None
    manager_model: str | None = None
    company_name: str | None = None
    company_mission: str | None = None
    director_name: str | None = None
    director_about: str | None = None
    accent_color: str | None = None
    specialists: list[str] | None = None


@app.post("/manager/config")
def manager_config_save(req: ManagerConfigUpdate, request: Request) -> dict:
    import manager_config as _mc
    user_id = _user_id_from_request(request)
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    cfg = _mc.save_config(user_id, updates)
    return {"config": cfg.to_dict(), "is_configured": True}


@app.get("/models")
def models_list() -> dict:
    """List models available to power the Manager (local + cloud)."""
    import manager_config as _mc
    return {"models": _mc.list_available_models()}


# ── Ollama auto-management ───────────────────────────────────────────────────

@app.get("/ollama/status")
def ollama_status() -> dict:
    """Quick probe + binary detection — used by the splash screen."""
    import ollama_launcher as _ol
    binary = _ol.locate_binary()
    return {
        "running": _ol.is_running(timeout=1.5),
        "installed": binary is not None,
        "binary": str(binary) if binary else None,
    }


@app.post("/ollama/start")
def ollama_start() -> dict:
    """Spawn `ollama serve` if needed and wait briefly for it to come up."""
    import ollama_launcher as _ol
    return _ol.start_if_needed(wait=True, max_wait_s=15.0)


@app.post("/models/warmup")
def models_warmup(request: Request) -> dict:
    """
    Pre-load a model into Ollama's VRAM so the next chat response is instant.
    Fires a background thread and returns immediately.
    """
    import threading, time as _t

    class _Body(BaseModel):
        model: str | None = None

    body_raw = {}
    try:
        import asyncio
        loop = asyncio.new_event_loop()
        body_raw = loop.run_until_complete(request.json())
        loop.close()
    except Exception:
        pass

    model_id = body_raw.get("model") if isinstance(body_raw, dict) else None
    if not model_id:
        import manager_config as _mc
        model_id = _mc.get_config("local-install").manager_model or "qwen2.5-coder:1.5b"

    def _do_warmup(model: str) -> None:
        try:
            import requests as _req
            _req.post(
                "http://127.0.0.1:11434/api/generate",
                json={"model": model, "prompt": "", "stream": False, "keep_alive": -1},
                timeout=90,
            )
            print(f"[warmup] {model} loaded")
        except Exception as e:
            print(f"[warmup] {model} failed: {e}")

    threading.Thread(target=_do_warmup, args=(model_id,), daemon=True).start()
    return {"ok": True, "model": model_id, "status": "warming_up"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("METIS_API_PORT", "7331"))
    uvicorn.run(app, host="127.0.0.1", port=port)
