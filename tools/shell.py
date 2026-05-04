"""
Host shell tool — Manus / Claude Code style, safe by default.

Every command:
    1. Is matched against an ALLOWLIST of known-safe program names.
    2. Is scanned for denied substrings (rm -rf /, format, mkfs, shutdown…).
    3. Is passed through `safety.confirm_gate` unless the caller explicitly
       opted in via `confirm=False` after reviewing the first-call token.
    4. Is audited with full stdout/stderr.
    5. Has an enforced timeout + max output size.

This is the muscle that lets Metis run `pytest`, `git status`, `npm run build`,
or `python your_script.py` the way Claude Code does — but with Manus-grade
caution so nothing gets destroyed by accident.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from safety import (
    audit,
    audited,
    confirm_gate,
    ConfirmRequired,
    rate_limit,
    redact,
    require_safe_path,
)


# ── Allow / deny lists ───────────────────────────────────────────────────────

ALLOWLIST = {
    # version control
    "git",
    # language runtimes
    "python", "python3", "py", "node", "deno", "bun",
    # package managers
    "pip", "pip3", "npm", "npx", "pnpm", "yarn", "uv", "poetry",
    # testing / linting
    "pytest", "mypy", "ruff", "black", "isort", "flake8", "eslint", "prettier",
    # builds
    "pyinstaller", "make", "cmake", "cargo", "go", "dotnet",
    # shell reads
    "ls", "dir", "pwd", "cat", "type", "head", "tail", "wc", "tree",
    "where", "which",
    # disk/process read-only
    "df", "du", "ps", "top", "whoami", "hostname",
    # networking (read-only)
    "ping", "curl", "wget", "nslookup", "dig",
    # metis
    "ollama", "streamlit", "uvicorn",
}

DENY_SUBSTRINGS = [
    "rm -rf /", "rm -rf ~", "rm -rf .",
    "> /dev/sda", "mkfs", "dd if=", "dd of=/dev",
    "shutdown", "reboot", "halt", "poweroff",
    "format c:", "format d:", "format /",
    "del /f /s /q c:", "rmdir /s /q c:", "rd /s /q c:",
    "chmod -R 000", "chown -R",
    ":(){ :|:& };:",   # fork bomb
    "curl | sh", "curl | bash", "wget | sh", "wget | bash",
    "netcat -l", "nc -l", "reverse-shell",
    "export OPENAI_API_KEY=",  # secret leaks
]

MAX_OUTPUT_BYTES = 200_000
DEFAULT_TIMEOUT = 60


class ShellBlocked(Exception):
    pass


def _program_name(cmd: str) -> str:
    try:
        parts = shlex.split(cmd, posix=(sys.platform != "win32"))
    except ValueError:
        parts = cmd.strip().split()
    return (parts[0] if parts else "").lower().replace(".exe", "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1]


def _check_allowed(cmd: str) -> None:
    lowered = cmd.lower()
    for bad in DENY_SUBSTRINGS:
        if bad in lowered:
            audit({"event": "shell_denied_substring", "substring": bad, "cmd_preview": cmd[:80]})
            raise ShellBlocked(f"Blocked: denied substring '{bad}'")
    prog = _program_name(cmd)
    if prog not in ALLOWLIST:
        audit({"event": "shell_denied_allowlist", "program": prog, "cmd_preview": cmd[:80]})
        raise ShellBlocked(
            f"Blocked: '{prog}' is not on the shell allowlist. "
            "Add it to tools.shell.ALLOWLIST if you trust it."
        )


# ── Public entry point ───────────────────────────────────────────────────────

@audited("shell.run")
def run(
    cmd: str,
    *,
    cwd: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    confirm: bool = True,
    confirm_token: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Execute `cmd` on the host.

    First call with `confirm=True` (default) and no `confirm_token` returns
    a token and raises `ConfirmRequired`. The UI surfaces that, the user
    approves, and the second call passes the token back to actually run.

    Passing `confirm=False` skips the gate — use only for programmatic calls
    you have already vetted (e.g. the autonomous loop after it planned).
    """
    if not rate_limit("shell.run", per_minute=30):
        raise ShellBlocked("Shell rate-limited: 30 commands/min max.")

    _check_allowed(cmd)

    if confirm:
        if confirm_token is None:
            tok = confirm_gate("shell.run", {"cmd": cmd, "cwd": cwd})
            raise ConfirmRequired(tok)
        confirm_gate("shell.run", {"cmd": cmd, "cwd": cwd}, token=confirm_token)

    work_dir = str(require_safe_path(cwd)) if cwd else None

    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=work_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env={**(env or {}), **_safe_env()},
        )
        stdout = redact(proc.stdout or "")[:MAX_OUTPUT_BYTES]
        stderr = redact(proc.stderr or "")[:MAX_OUTPUT_BYTES]
        return {
            "ok":          proc.returncode == 0,
            "exit_code":   proc.returncode,
            "stdout":      stdout,
            "stderr":      stderr,
            "cmd":         cmd,
            "cwd":         work_dir or str(Path.cwd()),
            "duration_ms": int((time.time() - started) * 1000),
        }
    except subprocess.TimeoutExpired:
        audit({"event": "shell_timeout", "cmd": cmd, "timeout": timeout})
        return {
            "ok":        False,
            "exit_code": 124,
            "stdout":    "",
            "stderr":    f"[shell] timeout after {timeout}s",
            "cmd":       cmd,
            "cwd":       work_dir or str(Path.cwd()),
        }


def _safe_env() -> dict[str, str]:
    """Inherit PATH / HOME / common OS vars but drop anything suspicious."""
    import os as _os
    keep = {
        "PATH", "PATHEXT", "SYSTEMROOT", "HOME", "USERPROFILE", "LOCALAPPDATA",
        "APPDATA", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE",
        "PYTHONIOENCODING", "PYTHONPATH", "OLLAMA_HOST",
    }
    return {k: v for k, v in _os.environ.items() if k in keep}


# ── Convenience helpers ──────────────────────────────────────────────────────

@audited("shell.run_trusted")
def run_trusted(cmd: str, *, cwd: str | None = None, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Pre-approved variant used by Metis's internal orchestrators only."""
    return run(cmd, cwd=cwd, timeout=timeout, confirm=False)


# ── CrewAI adapter ───────────────────────────────────────────────────────────

def as_crewai_tool():
    try:
        from crewai.tools import tool  # type: ignore
    except Exception:
        return None

    @tool("Shell")
    def _shell(command: str) -> str:
        """Run an allowlisted shell command. Returns JSON with stdout/stderr/exit_code."""
        import json as _json
        try:
            result = run(command, confirm=False)
        except ShellBlocked as e:
            return _json.dumps({"ok": False, "error": str(e)})
        return _json.dumps(result)

    return _shell
