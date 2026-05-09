"""
QQL - Quality Query Language for local Metis checks.

QQL is a tiny selector layer over the repo's quality and AI gates. It keeps
the commands discoverable without making developers remember every pytest,
Next, or AI smoke command.

Examples:
    python scripts/qql.py --list
    python scripts/qql.py ai.basic
    python scripts/qql.py ai.full,tests.backend
    python scripts/qql.py all --dry-run
    python scripts/qql.py ai.basic --json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).absolute().parent.parent


@dataclass(frozen=True)
class Check:
    key: str
    description: str
    command: tuple[str, ...]
    cwd: Path = ROOT


def _py(*args: str) -> tuple[str, ...]:
    return (sys.executable, *args)


CHECKS: dict[str, Check] = {
    "ai.basic": Check(
        key="ai.basic",
        description="Health, direct AI chat, and autonomous exact-answer missions.",
        command=_py("scripts/ai_smoke_gate.py"),
    ),
    "ai.full": Check(
        key="ai.full",
        description="ai.basic plus full manager orchestration chat.",
        command=_py("scripts/ai_smoke_gate.py", "--manager-chat"),
    ),
    "tests.backend": Check(
        key="tests.backend",
        description="Focused backend unit tests for AI, safety, reports, schedules, and contracts.",
        command=_py(
            "-m",
            "pytest",
            "tests/unit/test_autonomous_loop.py",
            "tests/unit/test_safety.py",
            "tests/unit/test_scheduled_job_reports.py",
            "tests/unit/test_run_contracts.py",
            "tests/unit/test_manager_run_artifacts.py",
            "-q",
        ),
    ),
    "tests.unit": Check(
        key="tests.unit",
        description="All configured Python unit tests.",
        command=_py("-m", "pytest", "tests/unit", "-q"),
    ),
    "quality.diff": Check(
        key="quality.diff",
        description="Git whitespace/conflict-marker check for current tracked diffs.",
        command=("git", "diff", "--check"),
    ),
    "ui.desktop.lint": Check(
        key="ui.desktop.lint",
        description="Desktop UI lint check.",
        command=("npm", "run", "lint"),
        cwd=ROOT / "desktop-ui",
    ),
    "ui.desktop.build": Check(
        key="ui.desktop.build",
        description="Desktop UI production build.",
        command=("npm", "run", "build"),
        cwd=ROOT / "desktop-ui",
    ),
}

ALIASES: dict[str, tuple[str, ...]] = {
    "ai": ("ai.basic",),
    "quality": ("quality.diff", "tests.backend"),
    "backend": ("tests.backend",),
    "ui": ("ui.desktop.lint", "ui.desktop.build"),
    "ui.desktop": ("ui.desktop.lint", "ui.desktop.build"),
    "all": ("quality.diff", "tests.backend", "ui.desktop.lint", "ui.desktop.build", "ai.basic"),
}


def available_checks() -> list[Check]:
    return [CHECKS[key] for key in sorted(CHECKS)]


def parse_query(query: str) -> list[Check]:
    raw_terms = [
        part.strip()
        for token in query.replace("+", ",").split(",")
        for part in token.split()
        if part.strip()
    ]
    if not raw_terms:
        raise ValueError("empty QQL query")

    selected: list[Check] = []
    seen: set[str] = set()
    for term in raw_terms:
        keys = ALIASES.get(term, (term,))
        for key in keys:
            check = CHECKS.get(key)
            if check is None:
                valid = ", ".join([*sorted(CHECKS), *sorted(ALIASES)])
                raise ValueError(f"unknown QQL selector {term!r}; valid selectors: {valid}")
            if check.key not in seen:
                selected.append(check)
                seen.add(check.key)
    return selected


def _display_command(check: Check) -> str:
    return " ".join(check.command)


def _resolved_command(command: tuple[str, ...]) -> tuple[str, ...]:
    executable = shutil.which(command[0])
    if executable is None:
        return command
    return (executable, *command[1:])


def _run_check(check: Check) -> int:
    try:
        return subprocess.run(_resolved_command(check.command), cwd=check.cwd, check=False).returncode
    except FileNotFoundError:
        print(f"[qql] missing executable: {check.command[0]}", file=sys.stderr)
        return 127


def run_checks(checks: Iterable[Check], *, dry_run: bool) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for check in checks:
        started = time.time()
        print(f"[qql] {check.key}: {_display_command(check)}", flush=True)
        rc = 0 if dry_run else _run_check(check)
        elapsed = time.time() - started
        status = "dry-run" if dry_run else ("ok" if rc == 0 else "failed")
        print(f"[qql] {check.key}: {status} ({elapsed:.1f}s)", flush=True)
        results.append({
            "key": check.key,
            "description": check.description,
            "command": list(check.command),
            "cwd": str(check.cwd),
            "returncode": rc,
            "status": status,
            "duration_s": round(elapsed, 3),
        })
        if rc != 0:
            break
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Metis quality checks by QQL selector.")
    parser.add_argument("query", nargs="?", default="quality", help="QQL selector, alias, or comma-separated selectors")
    parser.add_argument("--list", action="store_true", help="list checks and aliases")
    parser.add_argument("--dry-run", action="store_true", help="show selected checks without running them")
    parser.add_argument("--json", action="store_true", help="print machine-readable result JSON")
    args = parser.parse_args(argv)

    if args.list:
        print("Checks:")
        for check in available_checks():
            print(f"  {check.key:<14} {check.description}")
        print("Aliases:")
        for alias, keys in sorted(ALIASES.items()):
            print(f"  {alias:<14} {', '.join(keys)}")
        return 0

    try:
        checks = parse_query(args.query)
    except ValueError as exc:
        print(f"[qql] {exc}", file=sys.stderr)
        return 2

    results = run_checks(checks, dry_run=args.dry_run)
    if args.json:
        print(json.dumps({"query": args.query, "results": results}, indent=2))
    return 0 if all(int(row["returncode"]) == 0 for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
