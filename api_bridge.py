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
                "/money", "/people", "/automations",
                "/oauth/callback",
                "/auth/signup", "/auth/signin", "/auth/signout",
                "/auth/oauth/start", "/auth/oauth/complete",
                "/auth/me", "/auth/refresh", "/auth/reset_password",
                "/auth/local-token",
                # Ollama auto-start probes the splash screen calls before login
                "/ollama/status", "/ollama/start",
                # Playwright auto-install probes — same rationale (splash polls
                # them while the user is still on /login or /splash with no
                # session yet).
                "/playwright/status", "/playwright/install"}

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
    # Auto-install Playwright Chromium on first launch so customers never
    # need to run `python -m playwright install chromium` themselves.
    # ensure_chromium_async() is a no-op when the binary is already present.
    try:
        import playwright_installer as _pwi
        _pwi.ensure_chromium_async()
    except Exception as e:
        print(f"[api_bridge] playwright auto-install skipped: {e}")
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
                # Initial warm-up: load model permanently into VRAM
                _req.post("http://127.0.0.1:11434/api/generate",
                          json={"model": model, "prompt": "", "stream": False, "keep_alive": -1},
                          timeout=120)
                print(f"[api_bridge] model warmed up (permanent VRAM): {model}")
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
    # Group 6: per-specialist AGENTS.md overrides {name: md_text}.
    # Sent verbatim from the chat UI's right-click brief editor.
    agents_md_overrides: dict[str, str] | None = None
    # When the user is answering a specialist's [QUESTION]: from a previous
    # turn, the chat UI passes the answer + which specialist asked it so the
    # orchestrator can resume that subagent instead of starting fresh.
    director_answer: str | None = None
    director_answer_for: str | None = None
    direct: bool = False   # True = skip orchestrator, stream directly to model


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


# ── Tool permission policy ───────────────────────────────────────────────────
# Reports which channels the agent may use without re-asking. Group 1 added
# Chrome and Google services to this set (default-on per the operator).

@app.get("/policy")
def policy_get() -> dict:
    import comms_policy as _p
    return {
        "policy":   _p.get_policy(),
        "enforced": _p.policy_enforced(),
        "twilio_configured": _p.twilio_configured(),
        "smtp_configured":   _p.smtp_configured(),
        "google_oauth_configured": bool(
            os.getenv("GOOGLE_OAUTH_CLIENT_ID") and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
        ),
    }


class PolicyUpdate(BaseModel):
    sms: bool | None = None
    phone: bool | None = None
    email: bool | None = None
    calendar: bool | None = None
    chrome: bool | None = None
    google_services: bool | None = None


@app.post("/policy")
def policy_set(req: PolicyUpdate) -> dict:
    """Override the in-memory policy. Persists for the lifetime of this server."""
    import comms_policy as _p
    state = {
        "tool_sms":             req.sms             if req.sms             is not None else _p.is_allowed("sms"),
        "tool_phone_calls":     req.phone           if req.phone           is not None else _p.is_allowed("phone"),
        "tool_email":           req.email           if req.email           is not None else _p.is_allowed("email"),
        "tool_calendar":        req.calendar        if req.calendar        is not None else _p.is_allowed("calendar"),
        "tool_chrome":          req.chrome          if req.chrome          is not None else _p.is_allowed("chrome"),
        "tool_google_services": req.google_services if req.google_services is not None else _p.is_allowed("google_services"),
    }
    _p.set_from_session(state)
    return {"policy": _p.get_policy(), "enforced": True}


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
        # Instant heartbeat — browser knows we're alive before model loads
        yield f"data: {json.dumps({'type': 'heartbeat', 'message': 'Processing…'})}\n\n"

        # Direct mode: bypass orchestrator entirely — just stream tokens.
        # Used for Fast + Auto tiers where speed matters more than crew routing.
        use_direct = req.direct or req.role not in ("manager",)
        if use_direct:
            try:
                import manager_config as _mc
                cfg_obj = _mc.get_config(user_id)
                model_id = cfg_obj.manager_model or "qwen2.5-coder:1.5b"
                manager_name = cfg_obj.manager_name or "Metis"
                # Emit identity so UI can show manager name
                yield f"data: {json.dumps({'type': 'manager_identity', 'name': manager_name, 'model': model_id})}\n\n"
                import requests as _req
                t0 = __import__('time').time()
                r = _req.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={
                        "model": model_id,
                        "prompt": req.message,
                        "stream": True,
                        "keep_alive": -1,
                        "options": {"num_ctx": 4096},
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
                        yield f"data: {json.dumps({'type': 'done', 'duration_ms': dur_ms, 'agents_used': []})}\n\n"
                        break
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        elif req.role == "manager":
            from manager_orchestrator import orchestrate
            try:
                for ev in orchestrate(
                    req.message,
                    user_id=user_id,
                    session_id=req.session_id,
                    agents_md_overrides=req.agents_md_overrides,
                    director_answer=req.director_answer,
                    director_answer_for=req.director_answer_for,
                ):
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


# ── Web search ───────────────────────────────────────────────────────────────

class WebSearchRequest(BaseModel):
    query: str
    limit: int = 5


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
    name: str = ""
    description: str = ""
    agents_md: str = ""


class SchedulePatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    goal: str | None = None
    kind: str | None = None
    spec: str | None = None
    auto_approve: bool | None = None
    enabled: bool | None = None
    agents_md: str | None = None


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
        name=req.name,
        description=req.description,
        agents_md=req.agents_md,
    )
    return s.to_dict()


@app.patch("/schedules/{schedule_id}")
def schedules_patch(schedule_id: str, req: SchedulePatchRequest) -> dict:
    from scheduler import patch as _patch
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    s = _patch(schedule_id, updates)
    if not s:
        raise HTTPException(status_code=404, detail="schedule not found")
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


# ── Group 4: relationship updates + notes + conversation log ────────────────

class RelationshipPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    company: str | None = None
    phone: str | None = None
    email: str | None = None
    notes: str | None = None
    tags: list[str] | None = None
    folder: str | None = None       # optional folder grouping (Family / Work / etc.)
    avatar_color: str | None = None  # hex like #7C3AED


@app.patch("/relationships/{rid}")
def relationship_patch(rid: str, req: RelationshipPatch) -> dict:
    """Partial update — only fields the caller sets are merged."""
    fp = _RELATIONSHIPS_DIR / f"{rid}.json"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="relationship not found")
    data = json.loads(fp.read_text(encoding="utf-8"))
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    data.update(patch)
    data["updated_at"] = __import__("datetime").datetime.utcnow().isoformat()
    fp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


class NoteEntry(BaseModel):
    text: str


@app.post("/relationships/{rid}/notes")
def relationship_add_note(rid: str, req: NoteEntry) -> dict:
    """Append a timestamped note. Notes live as a list under data['notes_log']."""
    fp = _RELATIONSHIPS_DIR / f"{rid}.json"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="relationship not found")
    data = json.loads(fp.read_text(encoding="utf-8"))
    log = data.setdefault("notes_log", [])
    log.insert(0, {
        "id": __import__("uuid").uuid4().hex[:8],
        "ts": __import__("datetime").datetime.utcnow().isoformat(),
        "text": (req.text or "").strip(),
    })
    data["notes_log"] = log[:200]
    fp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"ok": True, "note": log[0]}


class ConversationEntry(BaseModel):
    channel: str        # "chat" | "email" | "sms" | "phone" | "in-person"
    direction: str      # "inbound" | "outbound"
    summary: str        # 1-2 line gist
    body: str = ""      # full content (optional)


@app.post("/relationships/{rid}/conversations")
def relationship_add_conversation(rid: str, req: ConversationEntry) -> dict:
    """Log a conversation. Used by the agent when it talks to/about this person."""
    fp = _RELATIONSHIPS_DIR / f"{rid}.json"
    if not fp.exists():
        raise HTTPException(status_code=404, detail="relationship not found")
    data = json.loads(fp.read_text(encoding="utf-8"))
    log = data.setdefault("conversations", [])
    log.insert(0, {
        "id": __import__("uuid").uuid4().hex[:8],
        "ts": __import__("datetime").datetime.utcnow().isoformat(),
        "channel": req.channel,
        "direction": req.direction,
        "summary": (req.summary or "").strip()[:240],
        "body": (req.body or "").strip()[:4000],
    })
    data["conversations"] = log[:500]
    fp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return {"ok": True, "entry": log[0]}


@app.get("/relationships/folders/list")
def relationship_folders() -> dict:
    """Aggregate folder + tag counts so the sidebar can render filters."""
    folders: dict[str, int] = {}
    tags: dict[str, int] = {}
    for f in _RELATIONSHIPS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        folder = (data.get("folder") or "Unsorted").strip() or "Unsorted"
        folders[folder] = folders.get(folder, 0) + 1
        for tag in (data.get("tags") or []):
            t = str(tag).strip()
            if t:
                tags[t] = tags.get(t, 0) + 1
    return {"folders": folders, "tags": tags}


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


@app.get("/auth/local-token")
def auth_local_token(request: Request) -> dict:
    """
    Bootstrap endpoint — returns the local install bearer token so the
    browser SPA can authenticate without a cloud account.

    SECURITY: Only reachable at 127.0.0.1 (the server binds to localhost
    only). External traffic never reaches this; there is no secret to leak.
    """
    host = request.headers.get("host", "")
    client_host = getattr(request.client, "host", "")
    # Block anything that isn't a loopback caller
    loopback = {"127.0.0.1", "localhost", "::1"}
    is_local = (
        any(h in host for h in loopback)
        or client_host in loopback
    )
    if not is_local:
        raise HTTPException(status_code=403, detail="local-only endpoint")
    token = auth_local.get_or_create()
    return {"token": token, "type": "local-install"}


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


# ── Vault (Group 2) ──────────────────────────────────────────────────────────
# Encrypted credential store. The master password never leaves the user's
# session; every endpoint requires the vault to be unlocked first
# (init creates + auto-unlocks; unlock confirms the password).

class VaultInitRequest(BaseModel):
    master_password: str


class VaultUnlockRequest(BaseModel):
    master_password: str


class VaultItemRequest(BaseModel):
    site: str
    username: str
    password: str
    url: str | None = ""
    notes: str | None = ""


class VaultRotateRequest(BaseModel):
    old_password: str
    new_password: str


@app.get("/vault/status")
def vault_status() -> dict:
    import vault as _vault
    return {
        "initialized": _vault.is_initialized(),
        "unlocked":    _vault.is_unlocked(),
        "idle_lock_s": _vault.IDLE_LOCK_S,
    }


@app.post("/vault/init")
def vault_init(req: VaultInitRequest) -> dict:
    import vault as _vault
    if _vault.is_initialized():
        raise HTTPException(status_code=409, detail="vault already initialized")
    try:
        _vault.init_vault(req.master_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "unlocked": True}


@app.post("/vault/unlock")
def vault_unlock(req: VaultUnlockRequest) -> dict:
    import vault as _vault
    ok = _vault.unlock(req.master_password)
    if not ok:
        raise HTTPException(status_code=401, detail="bad master password")
    return {"ok": True}


@app.post("/vault/lock")
def vault_lock() -> dict:
    import vault as _vault
    _vault.lock()
    return {"ok": True}


@app.get("/vault/items")
def vault_items_list() -> list[dict]:
    """Returns non-secret metadata for every stored credential."""
    import vault as _vault
    return _vault.list_items()


@app.post("/vault/items")
def vault_items_add(req: VaultItemRequest) -> dict:
    import vault as _vault
    try:
        item_id = _vault.add_item(req.model_dump())
    except PermissionError:
        raise HTTPException(status_code=423, detail="vault is locked")
    return {"ok": True, "id": item_id}


@app.get("/vault/items/{item_id}")
def vault_items_get(item_id: str) -> dict:
    import vault as _vault
    try:
        item = _vault.get_item(item_id)
    except PermissionError:
        raise HTTPException(status_code=423, detail="vault is locked")
    if not item:
        raise HTTPException(status_code=404, detail="item not found")
    return item


@app.delete("/vault/items/{item_id}")
def vault_items_delete(item_id: str) -> dict:
    import vault as _vault
    try:
        ok = _vault.delete_item(item_id)
    except PermissionError:
        raise HTTPException(status_code=423, detail="vault is locked")
    return {"ok": ok}


@app.post("/vault/rotate")
def vault_rotate(req: VaultRotateRequest) -> dict:
    import vault as _vault
    try:
        ok = _vault.rotate_master_password(req.old_password, req.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=401, detail="old password incorrect")
    return {"ok": True}


# ── Investing (Group 2 — paper trading sandbox, no KYC required) ────────────

class InvestWatchAdd(BaseModel):
    ticker: str


class InvestOrderRequest(BaseModel):
    ticker: str
    side: str        # "buy" | "sell"
    qty: float
    approval_token: str | None = ""


@app.get("/invest/portfolio")
def invest_portfolio() -> dict:
    import investing as _inv
    return _inv.portfolio()


@app.get("/invest/watchlist")
def invest_watchlist() -> list[dict]:
    import investing as _inv
    return _inv.get_watchlist()


@app.post("/invest/watchlist")
def invest_watchlist_add(req: InvestWatchAdd) -> dict:
    import investing as _inv
    return _inv.add_to_watchlist(req.ticker)


@app.delete("/invest/watchlist/{ticker}")
def invest_watchlist_remove(ticker: str) -> dict:
    import investing as _inv
    return {"ok": _inv.remove_from_watchlist(ticker)}


@app.get("/invest/quote/{ticker}")
def invest_quote(ticker: str) -> dict:
    import investing as _inv
    q = _inv.get_quote(ticker)
    if not q:
        raise HTTPException(status_code=404, detail="no quote")
    return q


@app.get("/invest/orders")
def invest_orders(limit: int = 50) -> list[dict]:
    import investing as _inv
    return _inv.list_orders(limit=limit)


@app.post("/invest/order")
def invest_order(req: InvestOrderRequest) -> dict:
    import investing as _inv
    result = _inv.submit_order(
        req.ticker, req.side, req.qty,
        approval_token=req.approval_token,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "order failed"))
    return result


@app.get("/invest/opportunities")
def invest_opportunities() -> list[dict]:
    import investing as _inv
    return _inv.list_opportunities()


# ── Group 3: AI scanner + proposal flow ─────────────────────────────────────

class InvestScanRequest(BaseModel):
    max_tickers: int = 10
    propose: bool = False        # if true, high-confidence picks become proposals


class InvestProposeRequest(BaseModel):
    ticker: str
    side: str                    # "buy" | "sell"
    qty: float
    reason: str = ""
    confidence: float = 0.5
    source: str = "manual"


class InvestSettingsUpdate(BaseModel):
    per_trade_cap_cents: int | None = None
    daily_cap_cents: int | None = None
    auto_approve_under_cents: int | None = None
    scan_interval_min: int | None = None
    notify_on_proposal: bool | None = None


@app.post("/invest/scan")
def invest_scan(req: InvestScanRequest) -> dict:
    """Run the AI scanner across the current watchlist + holdings."""
    import investing_scanner as _scan
    return _scan.scan_watchlist(max_tickers=req.max_tickers, propose=req.propose)


@app.get("/invest/proposals")
def invest_proposals_list(all: bool = False) -> list[dict]:
    """Pending proposals by default; pass ?all=true to include resolved ones."""
    import investing as _inv
    return _inv.list_all_proposals() if all else _inv.list_proposals()


@app.post("/invest/proposals")
def invest_propose(req: InvestProposeRequest) -> dict:
    """Manual proposal entry (e.g. from the chat — 'propose buy 5 AAPL')."""
    import investing as _inv
    r = _inv.propose_trade(
        req.ticker, req.side, req.qty,
        reason=req.reason, confidence=req.confidence, source=req.source,
    )
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r.get("error", "propose failed"))
    return r


@app.post("/invest/proposals/{proposal_id}/approve")
def invest_proposal_approve(proposal_id: str) -> dict:
    import investing as _inv
    r = _inv.approve_proposal(proposal_id)
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=(r.get("result") or {}).get("error") or r.get("error", "approve failed"))
    return r


@app.post("/invest/proposals/{proposal_id}/reject")
def invest_proposal_reject(proposal_id: str, note: str = "") -> dict:
    import investing as _inv
    return {"ok": _inv.reject_proposal(proposal_id, note=note)}


@app.get("/invest/settings")
def invest_settings_get() -> dict:
    import investing as _inv
    return _inv.get_settings()


@app.post("/invest/settings")
def invest_settings_update(req: InvestSettingsUpdate) -> dict:
    import investing as _inv
    return _inv.update_settings(req.model_dump(exclude_unset=True))


@app.get("/invest/analyze/{ticker}")
def invest_analyze(ticker: str) -> dict:
    """One-shot AI analysis on a single ticker (no side effects)."""
    import investing_scanner as _scan
    result = _scan.analyze_ticker(ticker)
    if not result:
        raise HTTPException(status_code=404, detail="no quote available")
    return result


# ── Group 8: Notifier + voice ───────────────────────────────────────────────

class NotifyRequest(BaseModel):
    subject: str
    body: str
    urgency: str = "normal"     # low | normal | high | critical
    user_id: str | None = None


@app.post("/notify")
def notify_send(req: NotifyRequest, request: Request) -> dict:
    """
    Send a notification through the Director's preferred channels.
    Used internally (proposal scanner, automation completion hooks) and
    exposed for the chat UI's "send me a reminder" command.
    """
    import notifier as _n
    uid = req.user_id or _user_id_from_request(request)
    return _n.notify(req.subject, req.body, urgency=req.urgency, user_id=uid)


@app.get("/notify/status")
def notify_status() -> dict:
    """Today's notification usage + remaining caps."""
    import notifier as _n
    return _n.status()


class VoiceCallRequest(BaseModel):
    to: str | None = None       # E.164; defaults to Director's notification_phone
    twiml_url: str | None = None


@app.post("/voice/call")
def voice_call(req: VoiceCallRequest, request: Request) -> dict:
    """
    Place an outbound voice call via Twilio.
    By default the Manager calls the Director's notification_phone, but the
    caller can override `to` to reach anyone (e.g. an agent calling a
    contact on the Director's behalf — gated by comms_policy('phone')).
    """
    import comms_policy as _cp
    if not _cp.is_allowed("phone"):
        raise HTTPException(status_code=403, detail="phone calls disabled in policy")

    target = (req.to or "").strip()
    if not target:
        # Default to the Director's notification phone
        try:
            import manager_config as _mc
            uid = _user_id_from_request(request)
            target = (_mc.get_config(uid).notification_phone or "").strip()
        except Exception:
            target = ""
    if not target:
        raise HTTPException(status_code=400, detail="no phone number — set notification_phone or pass `to`")

    try:
        from comms_link import CommsLink
        ok = CommsLink().place_outbound_call(target, twiml_url=req.twiml_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"call failed: {e}")
    return {"ok": bool(ok), "to": target}


class VoiceTwimlRequest(BaseModel):
    say: str                    # text the manager should speak
    voice: str = "Polly.Joanna" # any Twilio TTS voice; defaults to Polly.Joanna


@app.post("/voice/twiml")
def voice_twiml(req: VoiceTwimlRequest) -> dict:
    """
    Generate a TwiML <Response><Say> blob that Twilio will speak when it
    calls the recipient. Twilio fetches the TwiML URL during the call —
    operators host this somewhere reachable, or use the inline data: URL.

    Returns the raw XML string + a data URL the caller can plug into
    /voice/call's `twiml_url` field for one-shot announcements.
    """
    safe = (req.say or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    voice = req.voice or "Polly.Joanna"
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Say voice="{voice}">'
        '<prosody rate="medium">'
        # Required disclosure for AI-initiated calls (US 2-party consent
        # states + general best practice). Group 1's safety suggestions
        # called this out as mandatory.
        'This is an AI-generated call from your Metis assistant. '
        f'{safe}'
        '</prosody></Say></Response>'
    )
    import base64 as _b64
    data_url = "data:application/xml;base64," + _b64.b64encode(xml.encode("utf-8")).decode("ascii")
    return {"xml": xml, "data_url": data_url}


# ── Group 7: Browser control + assisted account creation ───────────────────
# A single shared session (one Playwright browser at a time). Multi-tab is
# fine inside the session; multiple sessions would fight over the lock.

_BROWSER_LOCK = asyncio.Lock()
_BROWSER_SESSION: Any = None
_BROWSER_PAGE: Any = None


class BrowserOpenRequest(BaseModel):
    headless: bool = False


class BrowserNavigateRequest(BaseModel):
    url: str


class BrowserFillRequest(BaseModel):
    selector: str
    value: str
    secret: bool = False


class BrowserClickRequest(BaseModel):
    selector: str


class BrowserAccountRequest(BaseModel):
    service: str             # short name, must be in METIS_BROWSER_ALLOWED_SERVICES
    username: str = ""
    email: str
    password: str
    signup_url: str = ""
    selectors: dict[str, str] | None = None
    submit_selector: str | None = None


@app.get("/browser/status")
def browser_status() -> dict:
    import browser_runner as _br
    return {
        "playwright_installed": _br.is_available(),
        "session_open":         _BROWSER_SESSION is not None,
        "allowed_services":     sorted(_br._allowed_services()),
        "daily_account_cap":    _br.DAILY_ACCOUNT_CAP,
        "daily_accounts_today": _br.daily_account_count(),
        "chrome_allowed":       __import__("comms_policy").is_allowed("chrome"),
    }


@app.post("/browser/open")
async def browser_open(req: BrowserOpenRequest) -> dict:
    """Spin up a Chromium session. Headful by default so the user sees it."""
    global _BROWSER_SESSION, _BROWSER_PAGE
    import browser_runner as _br
    if not _br.is_available():
        raise HTTPException(status_code=503,
            detail="Playwright not installed. Run `python -m playwright install chromium`.")
    import comms_policy as _cp
    if not _cp.is_allowed("chrome"):
        raise HTTPException(status_code=403, detail="Chrome control disabled in policy")
    async with _BROWSER_LOCK:
        if _BROWSER_SESSION is not None:
            return {"ok": True, "reused": True}
        sess = _br.BrowserSession()
        try:
            await sess.open(headless=req.headless)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"browser open failed: {e}")
        _BROWSER_SESSION = sess
        _BROWSER_PAGE = await sess.new_page()
    return {"ok": True, "reused": False}


@app.post("/browser/close")
async def browser_close() -> dict:
    global _BROWSER_SESSION, _BROWSER_PAGE
    async with _BROWSER_LOCK:
        if _BROWSER_SESSION:
            await _BROWSER_SESSION.close()
        _BROWSER_SESSION = None
        _BROWSER_PAGE = None
    return {"ok": True}


def _require_page() -> Any:
    if _BROWSER_SESSION is None or _BROWSER_PAGE is None:
        raise HTTPException(status_code=409, detail="no browser session — call /browser/open first")
    return _BROWSER_PAGE


@app.post("/browser/navigate")
async def browser_navigate(req: BrowserNavigateRequest) -> dict:
    import browser_runner as _br
    page = _require_page()
    return await _br.navigate(page, req.url)


@app.get("/browser/screenshot")
async def browser_screenshot() -> dict:
    import browser_runner as _br
    page = _require_page()
    b64 = await _br.screenshot_b64(page)
    return {"png_base64": b64}


@app.post("/browser/fill")
async def browser_fill(req: BrowserFillRequest) -> dict:
    import browser_runner as _br
    page = _require_page()
    await _br.fill(page, req.selector, req.value, secret=req.secret)
    return {"ok": True}


@app.post("/browser/click")
async def browser_click(req: BrowserClickRequest) -> dict:
    import browser_runner as _br
    page = _require_page()
    await _br.click(page, req.selector)
    return {"ok": True}


@app.post("/browser/create_account")
async def browser_create_account(req: BrowserAccountRequest) -> dict:
    import browser_runner as _br
    page = _require_page()
    result = await _br.create_account_assisted(
        page,
        service=req.service,
        username=req.username,
        email=req.email,
        password=req.password,
        signup_url=req.signup_url,
        selectors=req.selectors,
        submit_selector=req.submit_selector,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "account creation failed")
    return result


# ── Money / People / Automations pages (Group 1 scaffolds) ─────────────────
# Note: /relationships is already a JSON API. The HTML page lives at /people
# so browsers and API clients don't fight for the same route. The sidebar
# button still reads "Relationships" — the URL is internal.

@app.get("/money")
def page_money() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "money.html")


@app.get("/people")
def page_people() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "people.html")


@app.get("/automations")
def page_automations() -> FileResponse:
    return FileResponse(_FRONTEND_DIR / "automations.html")


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
    notification_email: str | None = None
    notification_phone: str | None = None
    notify_on_complete: bool | None = None
    notify_on_question: bool | None = None
    email_username: str | None = None
    email_password: str | None = None
    email_smtp_host: str | None = None
    email_smtp_port: int | None = None


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


# ── Playwright auto-install ─────────────────────────────────────────────────
# Surfaced through the splash screen so the customer sees "Installing browser
# engine — first launch only" without ever opening a terminal.

@app.get("/playwright/status")
def playwright_status() -> dict:
    """
    Live state of the Chromium auto-install. The splash polls this every
    second on first launch; once state == 'ready' it moves on.
    """
    import playwright_installer as _pwi
    return _pwi.install_status()


@app.post("/playwright/install")
def playwright_install() -> dict:
    """Manual trigger — useful if the auto-start was skipped."""
    import playwright_installer as _pwi
    return _pwi.ensure_chromium_async()


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
