"""
Multi-language code runner — Open Interpreter style.

One entry point, many languages. Each run is audited, sandbox-timed,
and output-capped. Supported out of the box:
    python         -> sys.executable
    javascript     -> node                 (if installed)
    typescript     -> npx tsx / deno       (if installed)
    bash / sh      -> bash                 (WSL on Windows, native on Linux/Mac)
    powershell     -> pwsh / powershell
    sql            -> sqlite3 via Python   (no external binary needed)
    ruby           -> ruby                 (if installed)
    go             -> go run               (if installed)

Every runner returns the same shape as skill_forge.run_in_sandbox():
    {"ok": bool, "stdout": str, "stderr": str, "exit_code": int,
     "mode": "subprocess|sqlite|docker", "duration_ms": int, "lang": str}
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from safety import audited


SUPPORTED = {"python", "javascript", "js", "typescript", "ts",
             "bash", "sh", "powershell", "ps", "ps1",
             "sql", "ruby", "go"}

DEFAULT_TIMEOUT = 30
MAX_OUTPUT_BYTES = 100_000


@audited("multilang.run")
def run(language: str, code: str, *, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    lang = (language or "").lower().strip()
    if lang in {"python", "py"}:
        return _run_interpreted("python", code, timeout=timeout, args=[sys.executable])
    if lang in {"javascript", "js"}:
        node = _which("node")
        if not node:
            return _err(lang, "node is not installed — run `choco install nodejs` or brew install node")
        return _run_file("js", code, "js", node, timeout)
    if lang in {"typescript", "ts"}:
        tsx = _which("tsx") or _which("deno")
        if not tsx:
            return _err(lang, "install tsx (`npm i -g tsx`) or deno")
        ext = "ts"
        if "deno" in tsx.lower():
            args = [tsx, "run", "--allow-read", "--allow-write"]
        else:
            args = [tsx]
        return _run_file(ext, code, ext, args, timeout)
    if lang in {"bash", "sh"}:
        bash = _which("bash")
        if not bash:
            return _err(lang, "bash not found (install Git Bash on Windows or use WSL)")
        return _run_file("sh", code, "sh", bash, timeout)
    if lang in {"powershell", "ps", "ps1"}:
        ps = _which("pwsh") or _which("powershell")
        if not ps:
            return _err(lang, "powershell not found")
        return _run_file("ps1", code, "ps1", [ps, "-NoLogo", "-NoProfile", "-File"], timeout)
    if lang == "sql":
        return _run_sqlite(code)
    if lang == "ruby":
        ruby = _which("ruby")
        if not ruby:
            return _err(lang, "ruby is not installed")
        return _run_file("rb", code, "rb", ruby, timeout)
    if lang == "go":
        go = _which("go")
        if not go:
            return _err(lang, "go is not installed")
        return _run_file("go", code, "go", [go, "run"], timeout)

    return _err(lang, f"unsupported language: {lang}. Supported: {', '.join(sorted(SUPPORTED))}")


# ── Internals ────────────────────────────────────────────────────────────────

def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _err(lang: str, msg: str) -> dict[str, Any]:
    return {"ok": False, "stdout": "", "stderr": msg, "exit_code": 127, "mode": "none", "lang": lang, "duration_ms": 0}


def _run_interpreted(
    lang: str,
    code: str,
    *,
    timeout: int,
    args: list[str] | str,
) -> dict[str, Any]:
    started = time.time()
    if isinstance(args, list):
        cmd = args + ["-c", code]
    else:
        cmd = [args, "-c", code]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "ok":          proc.returncode == 0,
            "stdout":      (proc.stdout or "")[:MAX_OUTPUT_BYTES],
            "stderr":      (proc.stderr or "")[:MAX_OUTPUT_BYTES],
            "exit_code":   proc.returncode,
            "mode":        "subprocess",
            "lang":        lang,
            "duration_ms": int((time.time() - started) * 1000),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"timeout after {timeout}s",
                "exit_code": 124, "mode": "subprocess", "lang": lang,
                "duration_ms": int((time.time() - started) * 1000)}


def _run_file(
    lang: str,
    code: str,
    ext: str,
    launcher: str | list[str],
    timeout: int,
) -> dict[str, Any]:
    started = time.time()
    with tempfile.NamedTemporaryFile("w", suffix=f".{ext}", delete=False, encoding="utf-8") as f:
        f.write(code)
        tmp = f.name
    try:
        cmd = (launcher if isinstance(launcher, list) else [launcher]) + [tmp]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "ok":          proc.returncode == 0,
            "stdout":      (proc.stdout or "")[:MAX_OUTPUT_BYTES],
            "stderr":      (proc.stderr or "")[:MAX_OUTPUT_BYTES],
            "exit_code":   proc.returncode,
            "mode":        "subprocess",
            "lang":        lang,
            "duration_ms": int((time.time() - started) * 1000),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"timeout after {timeout}s",
                "exit_code": 124, "mode": "subprocess", "lang": lang,
                "duration_ms": int((time.time() - started) * 1000)}
    finally:
        try:
            Path(tmp).unlink()
        except Exception:
            pass


def _run_sqlite(sql: str) -> dict[str, Any]:
    """Pure-Python SQLite — no external binary needed."""
    import sqlite3
    started = time.time()
    try:
        conn = sqlite3.connect(":memory:")
        cur = conn.cursor()
        lines: list[str] = []
        for statement in _split_sql(sql):
            try:
                cur.execute(statement)
            except Exception as e:
                return {"ok": False, "stdout": "\n".join(lines),
                        "stderr": f"SQL error on: {statement[:120]}\n{e}",
                        "exit_code": 1, "mode": "sqlite", "lang": "sql",
                        "duration_ms": int((time.time() - started) * 1000)}
            if cur.description:
                cols = [c[0] for c in cur.description]
                rows = cur.fetchall()
                lines.append("\t".join(cols))
                for row in rows:
                    lines.append("\t".join("" if v is None else str(v) for v in row))
                lines.append(f"-- {len(rows)} rows --")
        conn.commit()
        conn.close()
        return {"ok": True, "stdout": "\n".join(lines), "stderr": "",
                "exit_code": 0, "mode": "sqlite", "lang": "sql",
                "duration_ms": int((time.time() - started) * 1000)}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e),
                "exit_code": 1, "mode": "sqlite", "lang": "sql",
                "duration_ms": int((time.time() - started) * 1000)}


def _split_sql(sql: str) -> list[str]:
    out = [s.strip() for s in sql.split(";") if s.strip()]
    return out


# ── CrewAI tool adapter ──────────────────────────────────────────────────────

def as_crewai_tool():
    try:
        from crewai.tools import tool  # type: ignore
    except Exception:
        return None

    @tool("MultiLangRun")
    def _run(language: str, code: str) -> str:
        """Run code in python/js/ts/bash/powershell/sql/ruby/go. Returns JSON."""
        import json as _json
        return _json.dumps(run(language, code))

    return _run
