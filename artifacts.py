"""
Artifact store — the shared dataclass the UI's right-side pane watches.

Artifacts are how Metis returns "things you can look at": code files,
diffs, screenshots, generated images, charts, documents. Every artifact
lives as a JSON sidecar + the raw payload inside artifacts/.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from safety import PATHS


ArtifactType = Literal["code", "doc", "diff", "image", "chart", "upsell"]

ARTIFACTS_DIR = PATHS.artifacts


def _artifacts_dir() -> Path:
    return Path(PATHS.artifacts)


@dataclass
class Artifact:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    type: ArtifactType = "doc"
    title: str = "Untitled"
    language: str | None = None
    path: str | None = None            # path to the raw payload file, if any
    content: str | None = None         # inline text content (for small docs/code/diffs)
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


def _sidecar_path(artifact_id: str) -> Path:
    return _artifacts_dir() / f"{artifact_id}.json"


def save_artifact(artifact: Artifact) -> Artifact:
    """Write the sidecar JSON so the UI's watchdog picks it up."""
    _artifacts_dir().mkdir(parents=True, exist_ok=True)
    _sidecar_path(artifact.id).write_text(
        json.dumps(artifact.to_dict(), indent=2),
        encoding="utf-8",
    )
    return artifact


def list_artifacts(limit: int | None = 100) -> list[Artifact]:
    _artifacts_dir().mkdir(parents=True, exist_ok=True)
    rows: list[Artifact] = []
    for fp in _artifacts_dir().glob("*.json"):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            rows.append(Artifact(**data))
        except Exception:
            continue
    rows.sort(key=lambda a: a.created_at, reverse=True)
    if limit:
        rows = rows[:limit]
    return rows


def get_artifact(artifact_id: str) -> Artifact | None:
    fp = _sidecar_path(artifact_id)
    if not fp.exists():
        return None
    try:
        return Artifact(**json.loads(fp.read_text(encoding="utf-8")))
    except Exception:
        return None


def delete_artifact(artifact_id: str) -> bool:
    fp = _sidecar_path(artifact_id)
    if not fp.exists():
        return False
    try:
        fp.unlink()
    except Exception:
        return False
    return True
