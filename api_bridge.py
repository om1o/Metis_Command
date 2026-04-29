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
from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from brain_engine import ROLE_MODELS, list_local_models, stream_chat  # noqa: E402
from artifacts import list_artifacts, get_artifact  # noqa: E402
from metis_version import METIS_VERSION  # noqa: E402


import auth_local  # noqa: E402

app = FastAPI(title="Metis API Bridge", version="16.4.0")

PUBLIC_PATHS = {"/", "/health", "/version", "/status",
                "/docs", "/openapi.json", "/redoc",
                "/webhooks/stripe"}

app.version = METIS_VERSION


@app.middleware("http")
async def _auth_middleware(request, call_next):
    """Require Authorization: Bearer <token> on every protected route."""
    if request.url.path in PUBLIC_PATHS or request.method == "OPTIONS":
        return await call_next(request)
    authz = request.headers.get("authorization", "")
    token = (
        authz.split(" ", 1)[1].strip()
        if authz.lower().startswith("bearer ")
        else None
    )
    if not auth_local.verify(token):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            {"error": {"code": "unauthorized",
                       "message": "missing or invalid Metis local token"}},
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
def root() -> dict:
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
async def chat(req: ChatRequest) -> StreamingResponse:
    """Server-Sent Events stream of assistant tokens."""

    def sse() -> Any:
        for ev in stream_chat(
            req.role,
            [{"role": "user", "content": req.message}],
        ):
            yield f"data: {json.dumps(ev)}\n\n"
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
    from module_manager import plan_tier as _plan
    p = _plan(tier)
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
def sessions_list(limit: int = 50) -> list[str]:
    from memory import list_sessions
    try:
        return list(list_sessions(limit=limit) or [])
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"sessions backend unavailable: {e}")


@app.get("/sessions/{session_id}")
def sessions_load(session_id: str, limit: int = 200) -> list[dict]:
    from memory import load_session
    try:
        return list(load_session(session_id, limit=limit) or [])
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"session load failed: {e}")


@app.delete("/sessions/{session_id}")
def sessions_clear(session_id: str) -> dict:
    from memory import clear_session
    try:
        clear_session(session_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"session clear failed: {e}")
    return {"ok": True, "session_id": session_id}


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


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("METIS_API_PORT", "7331"))
    uvicorn.run(app, host="127.0.0.1", port=port)
