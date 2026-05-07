"""
Code Workspace Manager - owns the ~/MetisProjects/ tree of working folders
the AI can edit. Group 1 of the Code feature: just the shell.

Design rules
------------
1. Every workspace lives under METIS_PROJECTS_ROOT (default ~/MetisProjects).
   No path API ever accepts an absolute path from the client; everything is
   resolved relative to the active workspace and validated to be inside it.
2. Symlink escape is rejected: we resolve the real path and confirm it
   still starts with the workspace root.
3. Clone of public GitHub repos works without any token. If the repo is
   larger than SHALLOW_CLONE_THRESHOLD_BYTES (default 200 MB) we use
   `--depth 1` so a 5 GB monorepo does not eat the customer's disk.
4. Persistence: identity/code_workspaces.json - list of {slug, name,
   path, source ('local'|'github'), git_url?, created_at, last_opened_at}.
   Gitignored so user data never leaks into source.

Public API
----------
    root_dir() -> Path
    list_workspaces() -> list[dict]
    create_workspace(name) -> dict
    clone_workspace(git_url, name=None) -> dict
    delete_workspace(slug) -> bool
    open_workspace(slug) -> dict           # marks active + bumps last_opened_at
    active_workspace() -> dict | None
    workspace_path(slug) -> Path

    read_tree(slug, max_entries=5000) -> list[dict]
    read_file(slug, rel_path) -> str
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Configuration

DEFAULT_ROOT = Path.home() / "MetisProjects"
ROOT = Path(os.getenv("METIS_PROJECTS_ROOT", str(DEFAULT_ROOT))).resolve()
STATE_FILE = Path("identity") / "code_workspaces.json"

# Repos larger than this get cloned with --depth 1 so we do not eat the user's
# disk on a 5 GB monorepo. 200 MB feels right for the threshold; under that
# a full clone gives them history; over that, shallow clone keeps the first
# run bounded.
SHALLOW_CLONE_THRESHOLD_BYTES = int(os.getenv("METIS_SHALLOW_CLONE_BYTES", str(200 * 1024 * 1024)))

# File-tree filtering - these dirs cause out-of-control trees on most
# projects and rarely contain user-authored code worth showing in a tree.
TREE_SKIP_DIRS = {
    "node_modules", ".git", ".hg", ".svn", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "dist", "build", ".venv", "venv", "env",
    ".next", ".nuxt", ".turbo", ".cache", "coverage", ".idea", ".vscode",
    ".DS_Store", ".gradle", "target",
}
# Per-file size cap when reading: stop someone from /code/file?path=video.mp4
# accidentally pulling 200 MB into the editor.
MAX_READ_BYTES = int(os.getenv("METIS_MAX_READ_BYTES", str(2 * 1024 * 1024)))


def root_dir() -> Path:
    """Ensure the projects root exists and return it."""
    ROOT.mkdir(parents=True, exist_ok=True)
    return ROOT


# Persistence

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"workspaces": [], "active_slug": None}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        data.setdefault("workspaces", [])
        data.setdefault("active_slug", None)
        return data
    except Exception:
        return {"workspaces": [], "active_slug": None}


def _write_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# Helpers

_SLUG_RX = re.compile(r"[^a-zA-Z0-9_-]")


def _slugify(name: str) -> str:
    """Filesystem-safe slug. Always non-empty; falls back to a uuid prefix."""
    s = _SLUG_RX.sub("-", (name or "").strip()).strip("-")[:60]
    return s or f"workspace-{uuid.uuid4().hex[:8]}"


def _unique_slug(name: str, existing: set[str]) -> str:
    base = _slugify(name)
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def workspace_path(slug: str) -> Path:
    """Return the on-disk path for a workspace slug; create root if needed."""
    return root_dir() / _slugify(slug)


def _safe_subpath(slug: str, rel: str) -> Path:
    """
    Resolve `rel` inside the workspace folder for `slug`. Rejects any path
    that escapes the workspace root via .. or symlinks pointing outside.
    """
    base = workspace_path(slug).resolve()
    if not base.exists():
        raise FileNotFoundError(f"workspace not found: {slug}")
    candidate = (base / (rel or "").lstrip("/\\")).resolve()
    if not str(candidate).startswith(str(base)):
        raise PermissionError(f"path escapes workspace: {rel}")
    return candidate


# GitHub helpers

_GH_REPO_RX = re.compile(r"github\.com[/:]([^/]+)/([^/.\s]+)")


def _github_size_kb(git_url: str) -> int | None:
    """
    Hit the GitHub REST API to learn the repo's size in KB. Returns None on
    any failure (private repo without auth, network error, non-GitHub host).
    Used to decide whether to shallow-clone.
    """
    m = _GH_REPO_RX.search(git_url or "")
    if not m:
        return None
    owner, repo = m.group(1), m.group(2)
    try:
        import requests
        token = (os.getenv("GITHUB_TOKEN") or "").strip()
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}",
            headers=headers,
            timeout=8,
        )
        if r.status_code != 200:
            return None
        return int(r.json().get("size") or 0)
    except Exception:
        return None


# Public API

def list_workspaces() -> list[dict]:
    """Return registered workspaces, newest-first."""
    state = _read_state()
    out = list(state.get("workspaces") or [])
    out.sort(key=lambda w: w.get("last_opened_at") or w.get("created_at") or "", reverse=True)
    return out


def active_workspace() -> dict | None:
    state = _read_state()
    slug = state.get("active_slug")
    if not slug:
        return None
    return next((w for w in state.get("workspaces") or [] if w.get("slug") == slug), None)


def open_workspace(slug: str) -> dict:
    """Mark a workspace active + refresh last_opened timestamp."""
    state = _read_state()
    target = next((w for w in state.get("workspaces") or [] if w.get("slug") == slug), None)
    if not target:
        raise KeyError(f"unknown workspace: {slug}")
    target["last_opened_at"] = _now_iso()
    state["active_slug"] = slug
    _write_state(state)
    return target


def create_workspace(name: str) -> dict:
    """Make an empty folder + register it."""
    name = (name or "").strip()
    if not name:
        raise ValueError("workspace name required")
    state = _read_state()
    existing = {w["slug"] for w in state.get("workspaces") or []}
    slug = _unique_slug(name, existing)
    path = workspace_path(slug)
    path.mkdir(parents=True, exist_ok=True)
    entry = {
        "slug": slug,
        "name": name,
        "path": str(path),
        "source": "local",
        "git_url": "",
        "created_at": _now_iso(),
        "last_opened_at": _now_iso(),
    }
    state.setdefault("workspaces", []).append(entry)
    state["active_slug"] = slug
    _write_state(state)
    return entry


def clone_workspace(git_url: str, name: str | None = None) -> dict:
    """
    Clone a public GitHub (or any git) URL into the projects root.

    Returns the registered workspace dict. Raises RuntimeError if `git`
    isn't available or the clone fails.

    Auto-shallows if the repo is bigger than SHALLOW_CLONE_THRESHOLD_BYTES.
    Records {shallow: bool, size_kb: int|None} on the entry so the UI can
    offer "fetch full history" later.
    """
    git_url = (git_url or "").strip()
    if not git_url:
        raise ValueError("git URL required")
    if shutil.which("git") is None:
        raise RuntimeError("git is not installed on this machine")

    # Derive name + slug
    base = name or git_url.rstrip("/").split("/")[-1]
    base = re.sub(r"\.git$", "", base)
    state = _read_state()
    existing = {w["slug"] for w in state.get("workspaces") or []}
    slug = _unique_slug(base, existing)
    target = workspace_path(slug)
    if target.exists():
        # Shouldn't happen because of unique slug, but be defensive.
        raise RuntimeError(f"target path already exists: {target}")

    size_kb = _github_size_kb(git_url)
    shallow = bool(size_kb and (size_kb * 1024) > SHALLOW_CLONE_THRESHOLD_BYTES)
    cmd = ["git", "clone"]
    if shallow:
        cmd += ["--depth", "1"]
    cmd += [git_url, str(target)]

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )
    if proc.returncode != 0:
        # Clean up any partial directory the clone may have left.
        if target.exists():
            try:
                shutil.rmtree(target, ignore_errors=True)
            except Exception:
                pass
        raise RuntimeError(f"git clone failed: {(proc.stderr or proc.stdout or '').strip()[:400]}")

    entry = {
        "slug": slug,
        "name": base,
        "path": str(target),
        "source": "github",
        "git_url": git_url,
        "shallow": shallow,
        "size_kb": size_kb,
        "created_at": _now_iso(),
        "last_opened_at": _now_iso(),
    }
    state.setdefault("workspaces", []).append(entry)
    state["active_slug"] = slug
    _write_state(state)
    return entry


def delete_workspace(slug: str, *, remove_files: bool = False) -> bool:
    """
    Drop a workspace from the registry. Pass remove_files=True to also rm -rf
    the on-disk folder. Won't touch anything outside the projects root.
    """
    state = _read_state()
    before = len(state.get("workspaces") or [])
    state["workspaces"] = [w for w in (state.get("workspaces") or []) if w["slug"] != slug]
    if state.get("active_slug") == slug:
        state["active_slug"] = state["workspaces"][0]["slug"] if state["workspaces"] else None
    _write_state(state)
    if remove_files:
        path = workspace_path(slug)
        # Belt-and-braces: only delete if the path lives under our root.
        if str(path).startswith(str(root_dir())):
            try:
                shutil.rmtree(path, ignore_errors=True)
            except Exception:
                pass
    return len(state["workspaces"]) < before


# File tree + read

def read_tree(slug: str, max_entries: int = 5000) -> list[dict]:
    """
    Walk the workspace and return a flat list of entries:
        {"path": "src/app.py", "type": "file"|"dir", "size": int, "ext": "py"}

    Skips heavy dirs (node_modules, .git, ...). Caps at max_entries so a
    monstrous tree never lands in the UI's lap.
    """
    base = workspace_path(slug).resolve()
    if not base.exists():
        raise FileNotFoundError(slug)
    out: list[dict] = []
    for root, dirs, files in os.walk(base):
        # Filter dirs IN-PLACE so os.walk skips them.
        dirs[:] = sorted([d for d in dirs if d not in TREE_SKIP_DIRS])
        rel_root = Path(root).relative_to(base)
        for d in dirs:
            rel = (rel_root / d).as_posix()
            out.append({"path": rel, "type": "dir", "size": 0, "ext": ""})
            if len(out) >= max_entries:
                return out
        for f in sorted(files):
            rel = (rel_root / f).as_posix()
            try:
                size = (Path(root) / f).stat().st_size
            except Exception:
                size = 0
            ext = Path(f).suffix.lstrip(".").lower()
            out.append({"path": rel, "type": "file", "size": size, "ext": ext})
            if len(out) >= max_entries:
                return out
    return out


def read_file(slug: str, rel_path: str) -> str:
    """
    Return the contents of a file inside the workspace as text. Refuses
    to load files larger than MAX_READ_BYTES.
    """
    target = _safe_subpath(slug, rel_path)
    if not target.is_file():
        raise FileNotFoundError(rel_path)
    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        raise ValueError(f"file too large to display: {size} bytes")
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Best effort for binary-ish files: hex preview header.
        with target.open("rb") as f:
            head = f.read(min(size, 2048))
        return f"[binary file - {size} bytes]\nfirst {len(head)} bytes hex:\n{head.hex()}"
