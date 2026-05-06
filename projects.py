"""
Projects / Workspaces — Claude-Cowork-style shared context containers.

A Project bundles:
    - a name + description
    - custom system instructions ("You are working on the Metis codebase…")
    - an attached-files list (source documents the Scholar always has handy)
    - a pinned ChromaDB namespace so the memory loop can recall project-specific
      facts without mixing them with other projects

Directory layout on disk:
    identity/projects/<slug>/project.json
    identity/projects/<slug>/files/<uploaded files>
"""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from safety import audit, audited


PROJECTS_DIR = Path("identity") / "projects"


@dataclass
class Project:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    slug: str = "default"
    name: str = "Default"
    description: str = ""
    instructions: str = ""
    attachments: list[str] = field(default_factory=list)   # relative paths
    memory_namespace: str = ""                             # ChromaDB partition
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return (slug or "project")[:40]


def _project_dir(slug: str) -> Path:
    return PROJECTS_DIR / slug


def _project_file(slug: str) -> Path:
    return _project_dir(slug) / "project.json"


# ── Public API ───────────────────────────────────────────────────────────────

@audited("projects.create")
def create(
    name: str,
    *,
    description: str = "",
    instructions: str = "",
) -> Project:
    slug = _slugify(name)
    _project_dir(slug).mkdir(parents=True, exist_ok=True)
    (_project_dir(slug) / "files").mkdir(exist_ok=True)

    project = Project(
        slug=slug,
        name=name or slug,
        description=description,
        instructions=instructions,
        memory_namespace=f"project:{slug}",
    )
    _project_file(slug).write_text(
        json.dumps(project.to_dict(), indent=2),
        encoding="utf-8",
    )
    return project


@audited("projects.list")
def list_projects() -> list[Project]:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    out: list[Project] = []
    for sub in PROJECTS_DIR.iterdir():
        pf = sub / "project.json"
        if not pf.exists():
            continue
        try:
            data = json.loads(pf.read_text(encoding="utf-8"))
            out.append(Project(**data))
        except Exception:
            continue
    out.sort(key=lambda p: p.updated_at, reverse=True)
    return out


def get(slug: str) -> Project | None:
    pf = _project_file(slug)
    if not pf.exists():
        return None
    try:
        return Project(**json.loads(pf.read_text(encoding="utf-8")))
    except Exception:
        return None


@audited("projects.update_instructions")
def update_instructions(slug: str, instructions: str) -> Project | None:
    p = get(slug)
    if not p:
        return None
    p.instructions = instructions
    p.updated_at = time.time()
    _project_file(slug).write_text(json.dumps(p.to_dict(), indent=2), encoding="utf-8")
    return p


@audited("projects.attach")
def attach_file(slug: str, source_path: str) -> Project | None:
    p = get(slug)
    if not p:
        return None
    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(source_path)
    files_dir = _project_dir(slug) / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    dst = files_dir / src.name
    shutil.copy2(src, dst)
    rel = str(dst.relative_to(PROJECTS_DIR.parent))
    if rel not in p.attachments:
        p.attachments.append(rel)
    p.updated_at = time.time()
    _project_file(slug).write_text(json.dumps(p.to_dict(), indent=2), encoding="utf-8")
    return p


@audited("projects.detach")
def detach_file(slug: str, attachment: str) -> Project | None:
    p = get(slug)
    if not p or attachment not in p.attachments:
        return p
    p.attachments = [a for a in p.attachments if a != attachment]
    p.updated_at = time.time()
    _project_file(slug).write_text(json.dumps(p.to_dict(), indent=2), encoding="utf-8")
    return p


@audited("projects.delete")
def delete(slug: str) -> bool:
    d = _project_dir(slug)
    if not d.exists():
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True


# ── Active-project helpers ───────────────────────────────────────────────────

def active_slug() -> str | None:
    marker = PROJECTS_DIR / ".active"
    return marker.read_text(encoding="utf-8").strip() if marker.exists() else None


def set_active(slug: str) -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    (PROJECTS_DIR / ".active").write_text(slug, encoding="utf-8")


def active_project() -> Project | None:
    s = active_slug()
    return get(s) if s else None


def system_prompt_for(project: Project) -> str:
    """Render a ready-to-inject system message for chat/swarm sessions."""
    parts = [f"You are working inside the '{project.name}' project.", project.instructions or ""]
    if project.attachments:
        parts.append("Attached reference files:\n- " + "\n- ".join(project.attachments))
    if project.memory_namespace:
        parts.append(f"Use the `{project.memory_namespace}` memory namespace for recall.")
    return "\n\n".join(p for p in parts if p.strip())


def ingest_attachment(slug: str, attachment_rel: str) -> bool:
    """
    Parse an attachment and store it in the project's ChromaDB namespace
    so the Scholar agent can recall it later.
    """
    p = get(slug)
    if not p:
        return False
    path = PROJECTS_DIR.parent / attachment_rel
    if not path.exists():
        return False
    try:
        from tools.file_parser import parse
        parsed = parse(str(path))
        if not parsed.get("ok"):
            return False
        from memory_vault import MemoryBank
        bank = MemoryBank()
        # chunk the text into ~1k chunks for vector recall
        text = parsed.get("text", "")
        for i in range(0, len(text), 1200):
            chunk = text[i : i + 1200]
            entity = f"{p.memory_namespace}:{path.name}:{i//1200}"
            bank.store_interaction(entity_name=entity, facts=chunk)
        return True
    except Exception as e:
        audit({"event": "project_ingest_failed", "slug": slug, "file": attachment_rel, "error": str(e)})
        return False
