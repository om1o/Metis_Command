"""
Checkpoints — Cline-style undo + Manus-style replay.

Before any destructive action (Coder writing a file, shell run, skill forge)
Metis calls `snapshot()` which captures the contents of files touched by
the current mission. `undo_last()` or `undo_to(cp_id)` restores them.

Storage:
    logs/checkpoints/<cp_id>/manifest.json
    logs/checkpoints/<cp_id>/files/<relative path preserved>
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from safety import audit, audited, require_safe_path


CHECKPOINT_ROOT = Path("logs") / "checkpoints"
MAX_CHECKPOINTS = 50   # auto-prune anything older


@dataclass
class Checkpoint:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    label: str = ""
    mission_id: str | None = None
    files: list[str] = field(default_factory=list)    # relative paths preserved
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Snapshot ─────────────────────────────────────────────────────────────────

@audited("checkpoint.snapshot")
def snapshot(paths: list[str | Path], *, label: str = "", mission_id: str | None = None) -> Checkpoint:
    cp = Checkpoint(label=label, mission_id=mission_id)
    target_dir = CHECKPOINT_ROOT / cp.id
    (target_dir / "files").mkdir(parents=True, exist_ok=True)

    for raw in paths:
        src = require_safe_path(raw)
        if not src.exists():
            continue
        try:
            rel = src.relative_to(Path.cwd())
        except ValueError:
            continue  # outside cwd — skip for safety
        dst = target_dir / "files" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file():
            shutil.copy2(src, dst)
            cp.files.append(str(rel).replace("\\", "/"))
        # directories aren't auto-included; callers list files explicitly

    (target_dir / "manifest.json").write_text(
        json.dumps(cp.to_dict(), indent=2),
        encoding="utf-8",
    )
    _prune()
    return cp


# ── Restore ──────────────────────────────────────────────────────────────────

@audited("checkpoint.restore")
def restore(cp_id: str) -> dict[str, Any]:
    cp_dir = CHECKPOINT_ROOT / cp_id
    manifest = cp_dir / "manifest.json"
    if not manifest.exists():
        return {"ok": False, "error": "checkpoint not found"}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        cp = Checkpoint(**data)
    except Exception as e:
        return {"ok": False, "error": f"manifest unreadable: {e}"}

    restored: list[str] = []
    failed: list[dict[str, str]] = []
    for rel in cp.files:
        src = cp_dir / "files" / rel
        dst = Path.cwd() / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            restored.append(rel)
        except Exception as e:
            failed.append({"file": rel, "error": str(e)})

    return {"ok": not failed, "restored": restored, "failed": failed, "checkpoint": cp.id}


def undo_last() -> dict[str, Any]:
    latest = _latest_checkpoint()
    if latest is None:
        return {"ok": False, "error": "no checkpoints available"}
    return restore(latest.id)


def undo_to(cp_id: str) -> dict[str, Any]:
    return restore(cp_id)


# ── Listing ──────────────────────────────────────────────────────────────────

def list_checkpoints(limit: int = 20) -> list[Checkpoint]:
    CHECKPOINT_ROOT.mkdir(parents=True, exist_ok=True)
    cps: list[Checkpoint] = []
    for sub in CHECKPOINT_ROOT.iterdir():
        m = sub / "manifest.json"
        if not m.exists():
            continue
        try:
            cps.append(Checkpoint(**json.loads(m.read_text(encoding="utf-8"))))
        except Exception:
            continue
    cps.sort(key=lambda c: c.created_at, reverse=True)
    return cps[:limit]


def _latest_checkpoint() -> Checkpoint | None:
    rows = list_checkpoints(limit=1)
    return rows[0] if rows else None


def _prune() -> None:
    cps = list_checkpoints(limit=9999)
    for cp in cps[MAX_CHECKPOINTS:]:
        try:
            shutil.rmtree(CHECKPOINT_ROOT / cp.id, ignore_errors=True)
        except Exception:
            pass
