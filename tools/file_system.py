"""
File system tools — Claude Code / Cursor-style navigation.

Gives the Coder and Scholar agents first-class access to the user's
working directory in a safe, audited way:
    - read_file            line-range aware
    - write_file           creates dirs, confirm-gated outside workspace
    - list_dir             depth-limited glob
    - grep                 ripgrep fallback to Python regex
    - edit_file            old_string -> new_string replacement with uniqueness check
    - find_files           glob-based file discovery
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from safety import (
    audit,
    audited,
    confirm_gate,
    ConfirmRequired,
    require_safe_path,
)


MAX_READ_BYTES = 400_000
MAX_LINES = 4_000


# ── Read ─────────────────────────────────────────────────────────────────────

@audited("fs.read_file")
def read_file(path: str, *, offset: int = 1, limit: int | None = None) -> str:
    """
    Read a text file. Lines are 1-indexed and the output is annotated
    with a `LINE|CONTENT` prefix so agents can cite lines precisely.
    """
    p = require_safe_path(path)
    if not p.exists():
        return f"[fs] not found: {p}"
    if p.stat().st_size > MAX_READ_BYTES:
        raise ValueError(f"File too large for single read ({p.stat().st_size} bytes)")

    with p.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    start = max(0, offset - 1)
    end = len(lines) if limit is None else min(len(lines), start + limit)
    out = []
    for i in range(start, end):
        out.append(f"{i+1:>6}|{lines[i].rstrip()}")
    if end < len(lines):
        out.append(f"     …|[{len(lines) - end} more lines]")
    return "\n".join(out) or "[fs] empty file"


# ── Write ────────────────────────────────────────────────────────────────────

@audited("fs.write_file")
def write_file(path: str, content: str, *, confirm_token: str | None = None) -> dict[str, Any]:
    """
    Create or replace a text file. If the destination is outside the current
    workspace, the first call returns a confirm token and raises
    `ConfirmRequired`; pass `confirm_token=` on the second call to execute.
    """
    from pathlib import Path as _P
    p = _P(path).resolve()
    in_workspace = str(p).startswith(str(_P.cwd().resolve()))
    if not in_workspace:
        if confirm_token is None:
            tok = confirm_gate("fs.write_outside_workspace", {"path": str(p)})
            raise ConfirmRequired(tok)
        confirm_gate("fs.write_outside_workspace", {"path": str(p)}, token=confirm_token)

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(p), "bytes": len(content.encode("utf-8"))}


# ── Edit (Claude Code StrReplace semantics) ──────────────────────────────────

@audited("fs.edit_file")
def edit_file(path: str, old_string: str, new_string: str, *, replace_all: bool = False) -> dict[str, Any]:
    """
    Replace `old_string` with `new_string` in `path`. If `replace_all` is
    False (default), `old_string` must match exactly once — this is the
    Claude Code / Cursor discipline that prevents accidental mass edits.
    """
    p = require_safe_path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_string)
    if count == 0:
        return {"ok": False, "error": "old_string not found", "matches": 0}
    if count > 1 and not replace_all:
        return {"ok": False, "error": "old_string is not unique — pass replace_all=True", "matches": count}
    new_text = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
    p.write_text(new_text, encoding="utf-8")
    return {"ok": True, "path": str(p), "matches": count}


# ── List ─────────────────────────────────────────────────────────────────────

@audited("fs.list_dir")
def list_dir(path: str = ".", *, depth: int = 1, show_hidden: bool = False) -> list[dict[str, Any]]:
    """Return a list of {name, kind, size, depth, path} up to `depth` levels."""
    root = require_safe_path(path)
    if not root.exists():
        return []
    results: list[dict[str, Any]] = []
    skip = {"__pycache__", ".git", "metis-env", "node_modules", ".venv", "dist", "build"}

    def walk(node: Path, d: int) -> None:
        if d > depth:
            return
        try:
            for child in sorted(node.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                if not show_hidden and child.name.startswith("."):
                    continue
                if child.name in skip:
                    continue
                rel = child.relative_to(root)
                results.append({
                    "name":  child.name,
                    "path":  str(rel),
                    "kind":  "dir" if child.is_dir() else "file",
                    "size":  child.stat().st_size if child.is_file() else 0,
                    "depth": d,
                })
                if child.is_dir():
                    walk(child, d + 1)
        except PermissionError:
            return

    walk(root, 1)
    return results


# ── Grep ─────────────────────────────────────────────────────────────────────

@audited("fs.grep")
def grep(
    pattern: str,
    *,
    path: str = ".",
    glob: str | None = None,
    ignore_case: bool = False,
    max_results: int = 200,
) -> list[dict[str, Any]]:
    """
    Text search.  Prefers ripgrep (`rg`) when installed, falls back to a pure
    Python regex sweep so it always works.
    """
    root = require_safe_path(path)
    rg_path = _which("rg")
    if rg_path:
        args = [rg_path, "--json", "-n", "-H"]
        if ignore_case:
            args.append("-i")
        if glob:
            args += ["-g", glob]
        args += [pattern, str(root)]
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
            return _parse_rg(proc.stdout, limit=max_results)
        except Exception:
            pass

    # Python fallback
    flags = re.IGNORECASE if ignore_case else 0
    rx = re.compile(pattern, flags)
    hits: list[dict[str, Any]] = []
    for p in _walk_files(root, glob):
        try:
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if rx.search(line):
                    hits.append({
                        "path":  str(p.relative_to(root)),
                        "line":  i,
                        "match": line.strip()[:400],
                    })
                    if len(hits) >= max_results:
                        return hits
        except Exception:
            continue
    return hits


# ── Find ─────────────────────────────────────────────────────────────────────

@audited("fs.find_files")
def find_files(glob_pattern: str, *, path: str = ".") -> list[str]:
    """Glob-match files under `path`. Ignores venv / node_modules / cache dirs."""
    root = require_safe_path(path)
    pattern = glob_pattern if glob_pattern.startswith("**/") else f"**/{glob_pattern}"
    skip_parts = {"__pycache__", ".git", "metis-env", "node_modules", ".venv", "dist", "build"}
    return [
        str(p.relative_to(root))
        for p in root.glob(pattern)
        if p.is_file() and not any(part in skip_parts for part in p.parts)
    ]


# ── helpers ──────────────────────────────────────────────────────────────────

def _which(cmd: str) -> str | None:
    from shutil import which
    return which(cmd)


def _walk_files(root: Path, glob: str | None) -> list[Path]:
    skip = {"__pycache__", ".git", "metis-env", "node_modules", ".venv", "dist", "build"}
    pattern = glob or "**/*"
    if not pattern.startswith("**/"):
        pattern = f"**/{pattern}"
    return [
        p for p in root.glob(pattern)
        if p.is_file() and not any(part in skip for part in p.parts)
    ]


def _parse_rg(stdout: str, *, limit: int) -> list[dict[str, Any]]:
    import json as _json
    out: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            ev = _json.loads(line)
        except Exception:
            continue
        if ev.get("type") == "match":
            d = ev["data"]
            out.append({
                "path":  d["path"]["text"],
                "line":  d["line_number"],
                "match": (d.get("lines") or {}).get("text", "").rstrip()[:400],
            })
            if len(out) >= limit:
                break
    return out


# ── CrewAI adapters ──────────────────────────────────────────────────────────

def as_crewai_tools() -> list[Any]:
    try:
        from crewai.tools import tool  # type: ignore
    except Exception:
        return []

    @tool("ReadFile")
    def _read(path: str) -> str:
        """Read a text file. Path must be inside the current workspace."""
        return read_file(path)

    @tool("WriteFile")
    def _write(path: str, content: str) -> str:
        """Create or overwrite a file. Returns JSON status."""
        import json as _json
        return _json.dumps(write_file(path, content))

    @tool("EditFile")
    def _edit(path: str, old_string: str, new_string: str) -> str:
        """Replace the unique occurrence of old_string with new_string."""
        import json as _json
        return _json.dumps(edit_file(path, old_string, new_string))

    @tool("ListDir")
    def _ls(path: str = ".") -> str:
        """List files and directories beneath `path`."""
        import json as _json
        return _json.dumps(list_dir(path))

    @tool("Grep")
    def _grep(pattern: str, path: str = ".") -> str:
        """Search for `pattern` in text files under `path`."""
        import json as _json
        return _json.dumps(grep(pattern, path=path))

    @tool("FindFiles")
    def _find(glob_pattern: str, path: str = ".") -> str:
        """Glob-match files under `path`."""
        import json as _json
        return _json.dumps(find_files(glob_pattern, path=path))

    return [_read, _write, _edit, _ls, _grep, _find]
