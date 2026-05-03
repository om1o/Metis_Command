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
from fastapi.responses import StreamingResponse, FileResponse, RedirectResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from brain_engine import ROLE_MODELS, list_local_models, stream_chat  # noqa: E402
from artifacts import list_artifacts, get_artifact  # noqa: E402
from metis_version import METIS_VERSION  # noqa: E402


import auth_local  # noqa: E402
import auth_engine  # noqa: E402

app = FastAPI(title="Metis API Bridge", version="16.4.0")

# Frontend lives in ./frontend (HTML + static)
_FRONTEND_DIR = Path(__file__).parent / "frontend"

PUBLIC_PATHS = {"/", "/health", "/version", "/status",
                "/docs", "/openapi.json", "/redoc",
                "/webhooks/stripe",
                # Frontend pages + auth (no bearer token required)
                "/login", "/app", "/signup", "/setup", "/splash",
                "/oauth/callback",
                "/auth/signup", "/auth/signin", "/auth/signout",
                "/auth/oauth/start", "/auth/oauth/complete",
                "/auth/me", "/auth/refresh", "/auth/reset_password",
                # Ollama auto-start probes the splash screen calls before login
                "/ollama/status", "/ollama/start"}

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

    def sse() -> Any:
        full_answer = ""
        if req.role == "manager":
            from manager_orchestrator import orchestrate
            try:
                for ev in orchestrate(req.message, user_id=user_id, session_id=req.session_id):
                    if ev.get("type") == "token":
                        full_answer += ev.get("delta", "")
                    yield f"data: {json.dumps(ev)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        else:
            for ev in stream_chat(
                req.role,
                [{"role": "user", "content": req.message}],
            ):
                if ev.get("type") == "token":
                    full_answer += ev.get("delta", "")
                yield f"data: {json.dumps(ev)}\n\n"

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
        yield "event: close\ndata: {}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


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


# ── Schedules ────────────────────────────────────────────────────────────────

class ScheduleAddRequest(BaseModel):
    goal: str
    kind: str = "interval"  # interval | daily | once | cron
    spec: str = "60"
    project_slug: str | None = None
    auto_approve: bool = True
    action: str = ""


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


@app.post("/relationships")
def relationship_create(req: RelationshipCreate) -> dict:
    """Save a new relationship/contact."""
    import uuid
    rid = uuid.uuid4().hex[:12]
    data = req.dict()
    data["id"] = rid
    data["created_at"] = __import__("datetime").datetime.utcnow().isoformat()
    (_RELATIONSHIPS_DIR / f"{rid}.json").write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )
    return data


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


class ResetPasswordRequest(BaseModel):
    email: str


def _session_payload(session: Any) -> dict:
    if session is None:
        return {}
    return {
        "access_token": getattr(session, "access_token", None),
        "refresh_token": getattr(session, "refresh_token", None),
        "expires_at": getattr(session, "expires_at", None),
        "token_type": getattr(session, "token_type", "bearer"),
    }


def _user_payload(user: Any) -> dict:
    if user is None:
        return {}
    return {
        "id": getattr(user, "id", None),
        "email": getattr(user, "email", None),
        "created_at": str(getattr(user, "created_at", "") or ""),
        "user_metadata": getattr(user, "user_metadata", {}) or {},
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
        out = auth_engine.complete_oauth(code=req.code)
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
    app.mount(
        "/static",
        StaticFiles(directory=str(_FRONTEND_DIR / "static")),
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


@app.get("/logo-test")
def page_logo_test() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "logo-test.html")


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


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("METIS_API_PORT", "7331"))
    uvicorn.run(app, host="127.0.0.1", port=port)
