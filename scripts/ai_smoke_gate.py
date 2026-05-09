"""
AI smoke gate for local Metis development.

This is intentionally deterministic and failure-oriented. It checks that the
local API is reachable, the model can answer direct chat, and the autonomous
tool loop can ground exact answers from real files instead of hallucinating.

Usage:
    python scripts/ai_smoke_gate.py
    python scripts/ai_smoke_gate.py --manager-chat
    python scripts/ai_smoke_gate.py --direct-chat-repeats 3
    python scripts/ai_smoke_gate.py --report artifacts/quality/ai-smoke.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

import requests

ROOT = Path(__file__).absolute().parent.parent
API_BASE = os.getenv("METIS_API_BASE", "http://127.0.0.1:7331").rstrip("/")
TOKEN_FILE = ROOT / "identity" / "local_auth.token"
CheckFn = Callable[[], None]


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


def check_direct_chat_load(*, repeats: int) -> None:
    for index in range(1, repeats + 1):
        expected = f"METIS_LOAD_GATE_READY_{index}"
        answer, events = _stream_chat(
            {
                "session_id": f"ai-load-direct-{int(time.time())}-{index}",
                "message": f"Reply with exactly: {expected}",
                "role": "manager",
                "direct": True,
                "mode": "task",
                "permission": "read",
            },
            timeout_s=180,
        )
        if expected not in answer:
            _fail("direct chat load", f"run {index}: expected {expected!r}, got {answer!r}; events={events}")
        if "done" not in events:
            _fail("direct chat load", f"run {index}: missing done event; events={events}")
        _ok("direct chat load", expected)


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
    sys.modules.pop("autonomous_loop", None)
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
        heuristic_fn = getattr(autonomous_loop, "_heuristic_plan", None)
        if heuristic_fn is None:
            _fail("autonomous import", f"loaded {getattr(autonomous_loop, '__file__', '<unknown>')} without _heuristic_plan")
        heuristic_plan = heuristic_fn(goal)
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
            _fail("autonomous mission", f"{expected}: status={mission.status}, answer={mission.final_answer!r}; module={autonomous_loop.__file__}; plan={heuristic_plan}; steps={steps}")
        if mission.final_answer.strip() != expected:
            _fail("autonomous mission", f"expected {expected!r}, got {mission.final_answer!r}; module={autonomous_loop.__file__}; plan={heuristic_plan}; steps={steps}")
        _ok("autonomous mission", expected)


def selected_checks(*, manager_chat: bool, direct_chat_repeats: int = 1) -> list[tuple[str, CheckFn]]:
    checks: list[tuple[str, CheckFn]] = [
        ("system_health", check_health),
        ("direct_chat", check_direct_chat),
        ("autonomous_exact_answers", check_autonomous_exact_answers),
    ]
    if direct_chat_repeats > 1:
        checks.insert(2, (f"direct_chat_load_{direct_chat_repeats}", lambda: check_direct_chat_load(repeats=direct_chat_repeats)))
    if manager_chat:
        load_offset = 3 if direct_chat_repeats > 1 else 2
        checks.insert(load_offset, ("manager_chat", check_manager_chat))
    return checks


def run_gate(checks: Sequence[tuple[str, CheckFn]]) -> tuple[list[dict[str, object]], float]:
    started = time.time()
    results: list[dict[str, object]] = []
    for index, (name, check) in enumerate(checks):
        check_started = time.time()
        try:
            check()
        except Exception as exc:
            elapsed = time.time() - check_started
            print(f"[fail] {exc}", file=sys.stderr)
            results.append({
                "name": name,
                "status": "failed",
                "duration_s": round(elapsed, 3),
                "error": str(exc),
            })
            for skipped_name, _skipped_check in checks[index + 1:]:
                results.append({
                    "name": skipped_name,
                    "status": "skipped",
                    "duration_s": 0,
                    "reason": f"previous check failed: {name}",
                })
            break
        elapsed = time.time() - check_started
        results.append({
            "name": name,
            "status": "ok",
            "duration_s": round(elapsed, 3),
        })
    return results, time.time() - started


def environment_snapshot() -> dict[str, object]:
    return {
        "api_base": API_BASE,
        "metis_api_base_set": "METIS_API_BASE" in os.environ,
        "python": sys.executable,
        "platform": platform.platform(),
        "repo_root": str(ROOT),
        "token_file_exists": TOKEN_FILE.exists(),
    }


def build_report(
    *,
    manager_chat: bool,
    direct_chat_repeats: int,
    check_names: Sequence[str],
    results: list[dict[str, object]],
    duration_s: float,
) -> dict[str, object]:
    return {
        "schema": "metis.ai_smoke.report.v1",
        "ok": all(row["status"] == "ok" for row in results),
        "manager_chat": manager_chat,
        "direct_chat_repeats": direct_chat_repeats,
        "selected_checks": list(check_names),
        "api_base": API_BASE,
        "environment": environment_snapshot(),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "duration_s": round(duration_s, 3),
        "results": results,
    }


def write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manager-chat", action="store_true", help="also test full manager orchestration")
    parser.add_argument("--direct-chat-repeats", type=int, default=1, help="repeat direct chat for a light AI load gate")
    parser.add_argument("--json", action="store_true", help="print machine-readable report JSON")
    parser.add_argument("--report", type=Path, help="write a durable JSON report to this path")
    args = parser.parse_args(argv)
    if args.direct_chat_repeats < 1:
        parser.error("--direct-chat-repeats must be at least 1")

    checks = selected_checks(
        manager_chat=args.manager_chat,
        direct_chat_repeats=args.direct_chat_repeats,
    )
    results, duration_s = run_gate(checks)
    report = build_report(
        manager_chat=args.manager_chat,
        direct_chat_repeats=args.direct_chat_repeats,
        check_names=[name for name, _check in checks],
        results=results,
        duration_s=duration_s,
    )
    if args.report:
        write_report(args.report, report)
        print(f"[ok] ai smoke report: {args.report}")
    if args.json:
        print(json.dumps(report, indent=2))
    if report["ok"]:
        print(f"[ok] ai smoke gate complete in {duration_s:.1f}s")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
