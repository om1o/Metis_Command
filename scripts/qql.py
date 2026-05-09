"""
QQL - Quality Query Language for local Metis checks.

QQL is a tiny selector layer over the repo's quality and AI gates. It keeps
the commands discoverable without making developers remember every pytest,
Next, or AI smoke command.

Examples:
    python scripts/qql.py --list
    python scripts/qql.py ai.basic
    python scripts/qql.py ai.full,tests.backend
    python scripts/qql.py e2e
    python scripts/qql.py all --dry-run
    python scripts/qql.py quality --parallel
    python scripts/qql.py ai.basic --json
    python scripts/qql.py --doctor
    python scripts/qql.py --latest
    python scripts/qql.py --history
    python scripts/qql.py --summarize artifacts/quality/qql-e2e-latest.json
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


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
        command=_py("scripts/ai_smoke_gate.py", "--report", "artifacts/quality/ai-smoke-basic.json"),
    ),
    "ai.full": Check(
        key="ai.full",
        description="ai.basic plus full manager orchestration chat.",
        command=_py(
            "scripts/ai_smoke_gate.py",
            "--manager-chat",
            "--report",
            "artifacts/quality/ai-smoke-full.json",
        ),
    ),
    "ai.load": Check(
        key="ai.load",
        description="Health, repeated direct AI chat, and autonomous exact-answer missions.",
        command=_py(
            "scripts/ai_smoke_gate.py",
            "--direct-chat-repeats",
            "3",
            "--report",
            "artifacts/quality/ai-smoke-load.json",
        ),
    ),
    "tests.backend": Check(
        key="tests.backend",
        description="Focused backend unit tests for AI, safety, reports, schedules, auth, and contracts.",
        command=_py(
            "-m",
            "pytest",
            "tests/unit/test_autonomous_loop.py",
            "tests/unit/test_safety.py",
            "tests/unit/test_scheduled_job_reports.py",
            "tests/unit/test_run_contracts.py",
            "tests/unit/test_manager_run_artifacts.py",
            "tests/unit/test_setup_code_auth.py",
            "-q",
        ),
    ),
    "tests.qql": Check(
        key="tests.qql",
        description="QQL and release quality gate tests.",
        command=_py(
            "-m",
            "pytest",
            "tests/unit/test_qql.py",
            "tests/unit/test_release_gate.py",
            "tests/unit/test_ai_smoke_gate.py",
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
    "ai.e2e": ("quality.diff", "tests.qql", "tests.backend", "ui.desktop.lint", "ui.desktop.build", "ai.load"),
    "build": ("ui.desktop.lint", "ui.desktop.build"),
    "e2e": ("quality.diff", "tests.qql", "tests.backend", "ui.desktop.lint", "ui.desktop.build", "ai.load"),
    "load": ("ai.load",),
    "quality": ("quality.diff", "tests.qql", "tests.backend"),
    "backend": ("tests.backend",),
    "ui": ("ui.desktop.lint", "ui.desktop.build"),
    "ui.desktop": ("ui.desktop.lint", "ui.desktop.build"),
    "all": ("quality.diff", "tests.qql", "tests.backend", "ui.desktop.lint", "ui.desktop.build", "ai.load"),
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


def _run_check_captured(check: Check) -> tuple[int, str]:
    """Run a check and capture its combined stdout+stderr for atomic printing."""
    try:
        proc = subprocess.run(
            _resolved_command(check.command),
            cwd=check.cwd,
            check=False,
            capture_output=True,
            text=True,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode, output
    except FileNotFoundError:
        return 127, f"missing executable: {check.command[0]}\n"


def _git_value(args: Sequence[str]) -> str:
    try:
        proc = subprocess.run(
            ("git", *args),
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def run_checks(checks: Iterable[Check], *, dry_run: bool, parallel: bool = False) -> list[dict[str, object]]:
    check_list = list(checks)
    if parallel:
        return _run_checks_parallel(check_list, dry_run=dry_run)
    return _run_checks_sequential(check_list, dry_run=dry_run)


def _run_checks_sequential(checks: list[Check], *, dry_run: bool) -> list[dict[str, object]]:
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


def _run_checks_parallel(checks: list[Check], *, dry_run: bool) -> list[dict[str, object]]:
    """Run all checks concurrently; output from each check is printed atomically."""
    order = {check.key: i for i, check in enumerate(checks)}

    def _run_one(check: Check) -> dict[str, object]:
        started = time.time()
        if dry_run:
            rc, captured = 0, ""
        else:
            rc, captured = _run_check_captured(check)
        elapsed = time.time() - started
        status = "dry-run" if dry_run else ("ok" if rc == 0 else "failed")
        # Build output block and emit atomically so parallel lines don't interleave.
        lines = [f"[qql/p] {check.key}: {_display_command(check)}"]
        if captured:
            lines.extend(f"        {ln}" for ln in captured.rstrip().splitlines())
        lines.append(f"[qql/p] {check.key}: {status} ({elapsed:.1f}s)")
        print("\n".join(lines), flush=True)
        return {
            "key": check.key,
            "description": check.description,
            "command": list(check.command),
            "cwd": str(check.cwd),
            "returncode": rc,
            "status": status,
            "duration_s": round(elapsed, 3),
        }

    results_map: dict[str, dict[str, object]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(checks) or 1) as pool:
        futures = [pool.submit(_run_one, check) for check in checks]
        for fut in concurrent.futures.as_completed(futures):
            result = fut.result()
            results_map[str(result["key"])] = result
    return sorted(results_map.values(), key=lambda r: order[str(r["key"])])


def build_report(*, query: str, dry_run: bool, parallel: bool = False, results: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema": "metis.qql.report.v1",
        "query": query,
        "dry_run": dry_run,
        "parallel": parallel,
        "ok": all(int(row["returncode"]) == 0 for row in results),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repo": {
            "root": str(ROOT),
            "branch": _git_value(("branch", "--show-current")),
            "commit": _git_value(("rev-parse", "HEAD")),
        },
        "results": results,
    }


def write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def doctor_checks() -> list[dict[str, object]]:
    checks = [
        {
            "key": "python",
            "ok": bool(sys.executable) and Path(sys.executable).exists(),
            "detail": sys.executable,
        },
        {
            "key": "git",
            "ok": shutil.which("git") is not None,
            "detail": shutil.which("git") or "missing",
        },
        {
            "key": "npm",
            "ok": shutil.which("npm") is not None,
            "detail": shutil.which("npm") or "missing",
        },
        {
            "key": "desktop-ui",
            "ok": (ROOT / "desktop-ui" / "package.json").exists(),
            "detail": str(ROOT / "desktop-ui" / "package.json"),
        },
        {
            "key": "ai-smoke-gate",
            "ok": (ROOT / "scripts" / "ai_smoke_gate.py").exists(),
            "detail": str(ROOT / "scripts" / "ai_smoke_gate.py"),
        },
        {
            "key": "artifacts-ignored",
            "ok": _is_ignored(ROOT / "artifacts" / "quality" / "qql-doctor.json"),
            "detail": "artifacts/quality/qql-doctor.json",
        },
    ]
    return checks


def _is_ignored(path: Path) -> bool:
    try:
        proc = subprocess.run(
            ("git", "check-ignore", "-q", str(path)),
            cwd=ROOT,
            check=False,
        )
    except FileNotFoundError:
        return False
    return proc.returncode == 0


def build_doctor_report() -> dict[str, object]:
    checks = doctor_checks()
    return {
        "schema": "metis.qql.doctor.v1",
        "ok": all(bool(row["ok"]) for row in checks),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repo": {
            "root": str(ROOT),
            "branch": _git_value(("branch", "--show-current")),
            "commit": _git_value(("rev-parse", "HEAD")),
        },
        "checks": checks,
    }


def format_doctor_report(report: dict[str, object]) -> str:
    lines = [
        "[qql] doctor",
        f"status: {'ok' if report.get('ok') else 'failed'}",
    ]
    repo = report.get("repo") if isinstance(report.get("repo"), dict) else {}
    if repo:
        lines.append(f"repo: {repo.get('branch', '<unknown>')} @ {str(repo.get('commit', ''))[:12]}")
    for row in report.get("checks", []):
        if not isinstance(row, dict):
            continue
        mark = "ok" if row.get("ok") else "missing"
        lines.append(f"- {row.get('key', '<unknown>')}: {mark} ({row.get('detail', '')})")
    return "\n".join(lines)


def _fmt_duration(value: object) -> str:
    try:
        return f"{float(value):.1f}s"
    except (TypeError, ValueError):
        return "?s"


def summarize_report(path: Path) -> tuple[str, bool]:
    report = json.loads(path.read_text(encoding="utf-8"))
    schema = str(report.get("schema", "unknown"))
    ok = bool(report.get("ok"))
    status = "ok" if ok else "failed"
    lines = [f"[qql] summary: {path}", f"schema: {schema}", f"status: {status}"]

    if schema == "metis.qql.report.v1":
        repo = report.get("repo") if isinstance(report.get("repo"), dict) else {}
        lines.append(f"query: {report.get('query', '<unknown>')}")
        if repo:
            lines.append(f"repo: {repo.get('branch', '<unknown>')} @ {str(repo.get('commit', ''))[:12]}")
        for row in report.get("results", []):
            if not isinstance(row, dict):
                continue
            lines.append(
                f"- {row.get('key', '<unknown>')}: {row.get('status', '<unknown>')} "
                f"({_fmt_duration(row.get('duration_s'))})"
            )
    elif schema == "metis.ai_smoke.report.v1":
        lines.append(f"api_base: {report.get('api_base', '<unknown>')}")
        lines.append(f"direct_chat_repeats: {report.get('direct_chat_repeats', '<unknown>')}")
        selected = report.get("selected_checks")
        if isinstance(selected, list) and selected:
            lines.append(f"selected_checks: {', '.join(str(item) for item in selected)}")
        env = report.get("environment") if isinstance(report.get("environment"), dict) else {}
        if env:
            lines.append(f"python: {env.get('python', '<unknown>')}")
            lines.append(f"token_file_exists: {env.get('token_file_exists', '<unknown>')}")
        lines.append(f"duration: {_fmt_duration(report.get('duration_s'))}")
        for row in report.get("results", []):
            if not isinstance(row, dict):
                continue
            detail = f"- {row.get('name', '<unknown>')}: {row.get('status', '<unknown>')} ({_fmt_duration(row.get('duration_s'))})"
            if row.get("error"):
                detail += f" error={row.get('error')}"
            lines.append(detail)
    else:
        lines.append("results: unsupported report schema")
    return "\n".join(lines), ok


def latest_report_path(directory: Path | None = None) -> Path | None:
    report_dir = directory or (ROOT / "artifacts" / "quality")
    if not report_dir.exists():
        return None
    reports = [
        path
        for path in report_dir.glob("*.json")
        if path.is_file() and not path.name.endswith(".tmp")
    ]
    if not reports:
        return None
    return max(reports, key=lambda path: path.stat().st_mtime)


def report_history(directory: Path | None = None, *, limit: int = 8) -> list[Path]:
    report_dir = directory or (ROOT / "artifacts" / "quality")
    if not report_dir.exists():
        return []
    reports = [
        path
        for path in report_dir.glob("*.json")
        if path.is_file() and not path.name.endswith(".tmp")
    ]
    return sorted(reports, key=lambda path: path.stat().st_mtime, reverse=True)[:limit]


def format_history(paths: Sequence[Path]) -> str:
    if not paths:
        return "[qql] no reports found in artifacts/quality"
    lines = ["[qql] report history"]
    for path in paths:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            lines.append(f"- {path.name}: unreadable ({exc})")
            continue
        schema = str(report.get("schema", "unknown"))
        status = "ok" if report.get("ok") else "failed"
        label = str(report.get("query") or report.get("direct_chat_repeats") or schema)
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        lines.append(f"- {path.name}: {status} {label} {mtime}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Metis quality checks by QQL selector.")
    parser.add_argument("query", nargs="?", default="quality", help="QQL selector, alias, or comma-separated selectors")
    parser.add_argument("--list", action="store_true", help="list checks and aliases")
    parser.add_argument("--dry-run", action="store_true", help="show selected checks without running them")
    parser.add_argument("--parallel", action="store_true", help="run all selected checks concurrently (no fail-fast)")
    parser.add_argument("--doctor", action="store_true", help="check local QQL prerequisites without running gates")
    parser.add_argument("--json", action="store_true", help="print machine-readable result JSON")
    parser.add_argument("--report", type=Path, help="write a durable JSON quality report to this path")
    parser.add_argument("--latest", action="store_true", help="summarize the newest report in artifacts/quality")
    parser.add_argument("--history", action="store_true", help="list recent reports in artifacts/quality")
    parser.add_argument("--summarize", type=Path, help="print a concise summary for a QQL or AI smoke report")
    args = parser.parse_args(argv)

    if args.doctor:
        report = build_doctor_report()
        if args.report:
            write_report(args.report, report)
            print(f"[qql] report: {args.report}")
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(format_doctor_report(report))
        return 0 if report["ok"] else 1

    if args.latest:
        latest = latest_report_path()
        if latest is None:
            print("[qql] no reports found in artifacts/quality", file=sys.stderr)
            return 2
        try:
            summary, ok = summarize_report(latest)
        except Exception as exc:
            print(f"[qql] could not summarize {latest}: {exc}", file=sys.stderr)
            return 2
        print(summary)
        return 0 if ok else 1

    if args.history:
        paths = report_history()
        print(format_history(paths))
        return 0 if paths else 2

    if args.summarize:
        try:
            summary, ok = summarize_report(args.summarize)
        except Exception as exc:
            print(f"[qql] could not summarize {args.summarize}: {exc}", file=sys.stderr)
            return 2
        print(summary)
        return 0 if ok else 1

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

    results = run_checks(checks, dry_run=args.dry_run, parallel=args.parallel)
    report = build_report(query=args.query, dry_run=args.dry_run, parallel=args.parallel, results=results)
    if args.report:
        write_report(args.report, report)
        print(f"[qql] report: {args.report}")
    if args.json:
        print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
