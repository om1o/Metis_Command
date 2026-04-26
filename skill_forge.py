"""
Skill Forge — register, store, forge, and sandbox-execute Metis skills.

Pillars:
    - register(name)        decorator for in-process skills
    - invoke(name, **kw)    call a registered skill
    - forge_skill(goal)     ask Coder to WRITE a new skill, validate in sandbox
    - run_in_sandbox(code)  ephemeral Docker container (subprocess fallback)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any, Callable

from artifacts import Artifact, save_artifact

try:
    import docker  # type: ignore
except ImportError:
    docker = None  # type: ignore

from supabase_client import get_client


PLUGINS_DIR = Path("plugins")
SANDBOX_IMAGE = "python:3.12-slim"
SANDBOX_TIMEOUT = 10
SANDBOX_MEM_MB = 256


# In-process skill registry.
_registry: dict[str, Callable[..., Any]] = {}


def register(name: str, description: str = "") -> Callable:
    """Decorator to register a Python function as a Metis skill."""
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        _registry[name] = fn
        setattr(fn, "_metis_skill_description", description)
        return fn
    return decorator


def invoke(name: str, **kwargs: Any) -> Any:
    if name not in _registry:
        raise KeyError(f"[SkillForge] Skill '{name}' is not registered.")
    return _registry[name](**kwargs)


def list_skills() -> list[dict]:
    return [
        {
            "name": name,
            "description": getattr(fn, "_metis_skill_description", ""),
        }
        for name, fn in _registry.items()
    ]


# ── Supabase persistence ─────────────────────────────────────────────────────

def save_skill_to_db(name: str, description: str, code: str) -> dict:
    client = get_client()
    response = (
        client.table("skills")
        .upsert(
            {"name": name, "description": description, "code": code},
            on_conflict="name",
        )
        .execute()
    )
    return response.data[0] if response.data else {}


def load_skills_from_db() -> list[dict]:
    client = get_client()
    response = (
        client.table("skills")
        .select("name, description, code")
        .eq("enabled", True)
        .execute()
    )
    return response.data or []


# ── Sandbox execution ────────────────────────────────────────────────────────

def run_in_sandbox(
    code: str,
    timeout: int = SANDBOX_TIMEOUT,
    mem_mb: int = SANDBOX_MEM_MB,
) -> dict:
    """
    Execute arbitrary Python safely. Returns:
        {"ok": bool, "stdout": str, "stderr": str, "exit_code": int, "mode": str}
    Tries Docker first; falls back to a constrained subprocess with a warning.
    """
    started = time.time()
    if docker is not None:
        try:
            client = docker.from_env()
            container = client.containers.run(
                image=SANDBOX_IMAGE,
                command=["python", "-c", code],
                detach=True,
                network_mode="none",
                mem_limit=f"{mem_mb}m",
                nano_cpus=1_000_000_000,  # ~1 CPU
                stderr=True,
                stdout=True,
            )
            try:
                result = container.wait(timeout=timeout)
                logs = container.logs(stdout=True, stderr=True).decode("utf-8", "replace")
                exit_code = int(result.get("StatusCode", 1))
                return {
                    "ok": exit_code == 0,
                    "stdout": logs,
                    "stderr": "",
                    "exit_code": exit_code,
                    "mode": "docker",
                    "duration_ms": int((time.time() - started) * 1000),
                }
            finally:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
        except Exception as e:
            print(f"[SkillForge] Docker sandbox unavailable ({e}); falling back to subprocess.")

    # Subprocess fallback — less safe, but better than nothing on a user ThinkPad.
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name
    try:
        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "stdout": "[SANDBOX-WARNING: Docker unavailable, ran in host subprocess]\n"
                      + (proc.stdout or ""),
            "stderr": proc.stderr or "",
            "exit_code": proc.returncode,
            "mode": "subprocess",
            "duration_ms": int((time.time() - started) * 1000),
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"[SANDBOX-TIMEOUT] exceeded {timeout}s",
            "exit_code": 124,
            "mode": "subprocess",
            "duration_ms": int((time.time() - started) * 1000),
        }
    finally:
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass


# ── Forging new skills from natural language ─────────────────────────────────

_CODE_BLOCK = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_code(text: str) -> str:
    m = _CODE_BLOCK.search(text or "")
    return textwrap.dedent(m.group(1)).strip() if m else (text or "").strip()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "skill").lower()).strip("_")
    return (slug or "skill")[:40]


def forge_skill(goal: str) -> Artifact:
    """
    Ask the Coder agent to write a new skill satisfying `goal`,
    write it to plugins/<slug>.py, validate it in the sandbox,
    and return an Artifact describing the result.
    """
    from brain_engine import chat_by_role  # lazy import to avoid cycles

    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slugify(goal)
    path = PLUGINS_DIR / f"{slug}.py"

    prompt = (
        "Write a single self-contained Python module that satisfies this goal:\n"
        f"    {goal}\n\n"
        "Requirements:\n"
        "- Expose one primary function. Use type hints and a short docstring.\n"
        "- If the module reads inputs, include a runnable `__main__` block that "
        "demonstrates the function with safe sample values.\n"
        "- Do not import anything not in the Python standard library unless strictly required.\n"
        "- Return ONLY a single ```python``` code block, no commentary."
    )
    reply = chat_by_role("coder", [{"role": "user", "content": prompt}])
    code = _extract_code(reply)
    path.write_text(code, encoding="utf-8")

    sandbox_result = run_in_sandbox(code)
    artifact = Artifact(
        type="code",
        title=f"Skill: {goal[:60]}",
        language="python",
        path=str(path),
        content=code,
        metadata={
            "goal": goal,
            "slug": slug,
            "sandbox": sandbox_result,
        },
    )
    save_artifact(artifact)

    try:
        save_skill_to_db(slug, goal[:200], code)
    except Exception as e:
        print(f"[SkillForge] DB persist skipped: {e}")

    return artifact


# ── Built-in skills ──────────────────────────────────────────────────────────

@register("system_status", description="Return current hardware tier and active model.")
def system_status() -> dict:
    from hardware_scanner import get_hardware_tier
    from brain_engine import get_active_model
    return {
        "hardware_tier": get_hardware_tier(),
        "active_model": get_active_model("default"),
    }


@register("web_search", description="Search the web using DuckDuckGo.")
def web_search(query: str) -> str:
    from custom_tools import internet_search
    return internet_search.run(query) if hasattr(internet_search, "run") else str(internet_search(query))


@register("send_sms", description="Send an SMS via Twilio when enabled in Tools & outreach.")
def send_sms(phone_number: str, message: str) -> str:
    try:
        from comms_policy import is_allowed, policy_enforced, twilio_configured
        if policy_enforced() and not is_allowed("sms"):
            return "SMS is disabled: turn on **Text messages (SMS)** in the sidebar (Tools & outreach)."
        if not twilio_configured():
            return (
                "Twilio is not configured. Set TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM in `.env`, "
                "install `twilio`, and enable SMS in the sidebar."
            )
    except Exception:
        pass
    from comms_link import CommsLink
    ok = CommsLink().send_text_message(phone_number, message)
    return "SMS sent." if ok else "SMS failed (check Twilio credentials and policy)."


@register("send_email", description="Send email via SMTP when enabled in Tools & outreach.")
def send_email(to_email: str, subject: str, body: str) -> str:
    try:
        from comms_policy import is_allowed, policy_enforced, smtp_configured
        if policy_enforced() and not is_allowed("email"):
            return "Email is disabled: turn on **Email (SMTP)** in the sidebar (Tools & outreach)."
        if not smtp_configured():
            return "SMTP not configured. Set EMAIL_USER and EMAIL_PASS in `.env`."
    except Exception:
        pass
    from comms_link import CommsLink
    ok = CommsLink().send_human_email(to_email, subject, body)
    return "Email sent." if ok else "Email failed (check SMTP credentials)."


@register(
    "place_outbound_call",
    description="Start an outbound phone call via Twilio (needs TWILIO_CALL_TWIML_URL or twiml_url).",
)
def place_outbound_call(to_number: str, twiml_url: str = "") -> str:
    try:
        from comms_policy import is_allowed, policy_enforced, twilio_configured
        if policy_enforced() and not is_allowed("phone"):
            return "Outbound calls are disabled: turn on **Phone calls (outbound)** in the sidebar."
        if not twilio_configured():
            return "Twilio not fully configured. Set TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, and TWILIO_CALL_TWIML_URL."
    except Exception:
        pass
    from comms_link import CommsLink
    url = twiml_url.strip() or None
    ok = CommsLink().place_outbound_call(to_number, twiml_url=url)
    return "Call started." if ok else "Call not started (check Twilio + TwiML URL)."
