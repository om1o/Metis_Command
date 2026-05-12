"""
Agent tools — sandboxed file, terminal, and browser capabilities.

All file operations are sandboxed to allowed directories.
Terminal commands have timeouts and a denylist.
"""
from __future__ import annotations

import json
import subprocess
import re
from pathlib import Path


# ── Sandbox ──────────────────────────────────────────────────────────────

def _check_sandbox(path: str, roots: list[str]) -> Path:
    """Resolve path and verify it's under an allowed root. Raises ValueError if not."""
    p = Path(path).resolve()
    for root in roots:
        if str(p).startswith(str(Path(root).resolve())):
            return p
    raise ValueError(f"Path {path} is outside sandbox: {roots}")


# ── File tools ───────────────────────────────────────────────────────────

def file_read(path: str, sandbox_roots: list[str]) -> str:
    """Read a file. Returns content or error string."""
    try:
        p = _check_sandbox(path, sandbox_roots)
        if not p.exists():
            return f"[Error] File not found: {path}"
        return p.read_text(encoding="utf-8", errors="replace")[:50000]  # 50k char cap
    except Exception as e:
        return f"[Error] {e}"


def file_write(path: str, content: str, sandbox_roots: list[str]) -> str:
    """Write content to a file. Creates parent dirs if needed."""
    try:
        p = _check_sandbox(path, sandbox_roots)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"[OK] Written {len(content)} chars to {path}"
    except Exception as e:
        return f"[Error] {e}"


def file_edit(path: str, old: str, new: str, sandbox_roots: list[str]) -> str:
    """Search-and-replace edit in a file."""
    try:
        p = _check_sandbox(path, sandbox_roots)
        if not p.exists():
            return f"[Error] File not found: {path}"
        text = p.read_text(encoding="utf-8")
        if old not in text:
            return f"[Error] old_string not found in {path}"
        updated = text.replace(old, new, 1)
        p.write_text(updated, encoding="utf-8")
        return f"[OK] Edited {path}"
    except Exception as e:
        return f"[Error] {e}"


# ── Terminal ─────────────────────────────────────────────────────────────

_DENY_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"format\s+[a-z]:",
    r"del\s+/[sfq]",
    r"mkfs\.",
    r"dd\s+if=",
    r"shutdown",
    r"reboot",
]

def terminal_exec(cmd: str, cwd: str | None = None, timeout: int = 30) -> dict:
    """Execute a shell command with timeout. Returns {stdout, stderr, returncode}."""
    for pat in _DENY_PATTERNS:
        if re.search(pat, cmd, re.IGNORECASE):
            return {"stdout": "", "stderr": f"[Blocked] Dangerous command: {cmd}", "returncode": -1}
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd,
        )
        return {
            "stdout": result.stdout[:20000],
            "stderr": result.stderr[:5000],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"[Timeout] Command exceeded {timeout}s", "returncode": -1}
    except Exception as e:
        return {"stdout": "", "stderr": f"[Error] {e}", "returncode": -1}


# ── Browser ──────────────────────────────────────────────────────────────

def browser_fetch(url: str) -> dict:
    """Fetch a URL and return text content."""
    import requests
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "MetisAgent/1.0"})
        r.raise_for_status()
        text = r.text
        # Basic HTML stripping
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return {"text": text[:30000], "status": r.status_code, "url": url}
    except Exception as e:
        return {"text": f"[Error] {e}", "status": 0, "url": url}


# ── Tool schemas (OpenAI function-calling format) ────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read a file's contents",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path to read"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write content to a file (creates if needed)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_edit",
            "description": "Search-and-replace edit in a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "old": {"type": "string", "description": "Text to find"},
                    "new": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminal_exec",
            "description": "Execute a shell command",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Command to run"},
                    "cwd": {"type": "string", "description": "Working directory (optional)"},
                },
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fetch",
            "description": "Fetch a URL and return its text content",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "URL to fetch"}},
                "required": ["url"],
            },
        },
    },
]


def execute_tool(name: str, args: dict, sandbox_roots: list[str]) -> str:
    """Dispatch a tool call by name. Returns result string."""
    if name == "file_read":
        return file_read(args["path"], sandbox_roots)
    elif name == "file_write":
        return file_write(args["path"], args["content"], sandbox_roots)
    elif name == "file_edit":
        return file_edit(args["path"], args["old"], args["new"], sandbox_roots)
    elif name == "terminal_exec":
        result = terminal_exec(args["cmd"], args.get("cwd"))
        return json.dumps(result)
    elif name == "browser_fetch":
        result = browser_fetch(args["url"])
        return json.dumps(result)
    return f"[Error] Unknown tool: {name}"
