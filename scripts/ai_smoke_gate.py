"""
AI smoke gate for local Metis development.

This is intentionally deterministic and failure-oriented. It checks that the
local API is reachable, the model can answer direct chat, and the autonomous
tool loop can ground exact answers from real files instead of hallucinating.

Usage:
    python scripts/ai_smoke_gate.py
    python scripts/ai_smoke_gate.py --manager-chat
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
API_BASE = os.getenv("METIS_API_BASE", "http://127.0.0.1:7331").rstrip("/")
TOKEN_FILE = ROOT / "identity" / "local_auth.token"


def _token() -> str:
    try:
        response = requests.get(f"{API_BASE}/auth/local-token", timeout=10)
        if response.status_code == 200:
            token = str(response.json().get("token", "")).strip()
            if token:
                return token
    except Exception:
        pass
    return TOKEN_FILE.read_text(encoding="utf-8").strip()


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token()}",
        "Content-Type": "application/json",
    }


def _ok(name: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    print(f"[ok] {name}{suffix}")


def _fail(name: str, detail: str) -> None:
    raise AssertionError(f"{name}: {detail}")


def check_health() -> None:
    health = requests.get(f"{API_BASE}/health", timeout=8)
    if health.status_code != 200 or not health.json().get("ok"):
        _fail("health", f"bad response {health.status_code}: {health.text[:200]}")
    system = requests.get(f"{API_BASE}/system/health", headers=_headers(), timeout=30)
    if system.status_code != 200:
        _fail("system health", f"bad response {system.status_code}: {system.text[:200]}")
    body = system.json()
    if not body.get("preferred_manager"):
        _fail("system health", "no manager-capable provider is ready")
    _ok("system health", f"preferred_manager={body.get('preferred_manager')}")


def _stream_chat(payload: dict[str, Any], *, timeout_s: int) -> tuple[str, list[str]]:
    answer: list[str] = []
    events: list[str] = []
    with requests.post(
        f"{API_BASE}/chat",
        headers=_headers(),
        json=payload,
        stream=True,
        timeout=(10, timeout_s),
    ) as response:
        if response.status_code != 200:
            _fail("chat", f"bad response {response.status_code}: {response.text[:200]}")
        for raw in response.iter_lines(decode_unicode=True):
            if not raw or not raw.startswith("data: "):
                continue
            event = json.loads(raw[6:])
            kind = str(event.get("type", ""))
            events.append(kind)
            if kind == "token":
                answer.append(str(event.get("delta", "")))
            if kind == "error":
                _fail("chat", str(event.get("message", "unknown error")))
            if kind == "done":
                break
    return "".join(answer).strip(), events


def check_direct_chat() -> None:
    expected = "METIS_DIRECT_GATE_READY"
    answer, events = _stream_chat(
        {
            "session_id": f"ai-smoke-direct-{int(time.time())}",
            "message": f"Reply with exactly: {expected}",
            "role": "manager",
            "direct": True,
            "mode": "task",
            "permission": "read",
        },
        timeout_s=180,
    )
    if expected not in answer:
        _fail("direct chat", f"expected {expected!r}, got {answer!r}; events={events}")
    if "done" not in events:
        _fail("direct chat", f"missing done event; events={events}")
    _ok("direct chat", expected)


def check_manager_chat() -> None:
    expected = "METIS_MANAGER_GATE_READY"
    answer, events = _stream_chat(
        {
            "session_id": f"ai-smoke-manager-{int(time.time())}",
            "message": f"Reply with exactly: {expected}. Do not use tools.",
            "role": "manager",
            "direct": False,
            "mode": "task",
            "permission": "read",
        },
        timeout_s=260,
    )
    if expected not in answer:
        _fail("manager chat", f"expected {expected!r}, got {answer!r}; events={events}")
    if "manager_plan" not in events or "done" not in events:
        _fail("manager chat", f"missing manager/done events; events={events}")
    _ok("manager chat", expected)


def check_autonomous_exact_answers() -> None:
    sys.path.insert(0, str(ROOT))
    import autonomous_loop

    goals = [
        (
            "Find the package name in desktop-ui/package.json. Use tools if needed and answer with only the package name.",
            "desktop-ui",
        ),
        (
            "Find the package version in desktop-ui/package.json. Use tools if needed and answer with only the version string.",
            "0.1.0",
        ),
    ]
    for goal, expected in goals:
        mission = autonomous_loop.run_mission(
            goal,
            max_steps=3,
            auto_approve=False,
            session_id=f"ai-smoke-autonomous-{expected}",
        )
        steps = [
            {
                "index": step.index,
                "tool": step.tool,
                "ok": step.ok,
                "args": step.args,
                "observation": str(step.observation)[:220],
            }
            for step in mission.steps
        ]
        if mission.status != "success":
            _fail("autonomous mission", f"{expected}: status={mission.status}, answer={mission.final_answer!r}; steps={steps}")
        if mission.final_answer.strip() != expected:
            _fail("autonomous mission", f"expected {expected!r}, got {mission.final_answer!r}; steps={steps}")
        _ok("autonomous mission", expected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manager-chat", action="store_true", help="also test full manager orchestration")
    args = parser.parse_args()

    checks = [check_health, check_direct_chat, check_autonomous_exact_answers]
    if args.manager_chat:
        checks.insert(2, check_manager_chat)

    started = time.time()
    try:
        for check in checks:
            check()
    except Exception as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        return 1
    print(f"[ok] ai smoke gate complete in {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
