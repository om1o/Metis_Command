"""
Mission Concurrency Pool — Manus-style parallel autonomous tasks.

Lets the Director fire-and-forget N missions that run in parallel, with
live status polling from the UI ("Mission #3 · step 4/10 · Coder active").
Each submission is tracked in-memory by id; persistent history lives in
`logs/missions.jsonl` for replay and the `/replay <id>` command.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from safety import audit


MISSIONS_LOG = Path("logs") / "missions.jsonl"


@dataclass
class MissionRecord:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    goal: str = ""
    status: str = "queued"       # queued | running | success | failed | cancelled
    tag: str = ""
    project_slug: str | None = None
    auto_approve: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    submitted_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MissionPool:
    """ThreadPoolExecutor that knows how to run an autonomous_loop mission."""

    def __init__(self, max_workers: int = 3) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers,
                                            thread_name_prefix="MetisMission")
        self._records: dict[str, MissionRecord] = {}
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()

    # ── submission ──────────────────────────────────────────────────────────
    def submit(
        self,
        goal: str,
        *,
        tag: str = "",
        auto_approve: bool = False,
        project_slug: str | None = None,
    ) -> MissionRecord:
        record = MissionRecord(
            goal=goal,
            tag=tag,
            project_slug=project_slug,
            auto_approve=auto_approve,
        )
        with self._lock:
            self._records[record.id] = record

        def run() -> None:
            from autonomous_loop import run_mission
            with self._lock:
                record.status = "running"
                record.started_at = time.time()
            try:
                on_event = record.events.append
                mission = run_mission(
                    goal=goal,
                    auto_approve=auto_approve,
                    on_event=on_event,
                )
                with self._lock:
                    record.status = mission.status
                    record.final_answer = mission.final_answer
            except Exception as e:
                with self._lock:
                    record.status = "failed"
                    record.final_answer = f"{type(e).__name__}: {e}"
                audit({"event": "mission_worker_error", "id": record.id, "error": str(e)})
            finally:
                with self._lock:
                    record.ended_at = time.time()
                self._persist(record)

        future = self._executor.submit(run)
        with self._lock:
            self._futures[record.id] = future
        audit({"event": "mission_submitted", "id": record.id, "goal": goal[:120], "tag": tag})
        return record

    def get(self, mission_id: str) -> MissionRecord | None:
        with self._lock:
            return self._records.get(mission_id)

    def list(self, *, limit: int = 50) -> list[MissionRecord]:
        with self._lock:
            rows = list(self._records.values())
        rows.sort(key=lambda r: r.submitted_at, reverse=True)
        return rows[:limit]

    def cancel(self, mission_id: str) -> bool:
        with self._lock:
            future = self._futures.get(mission_id)
            record = self._records.get(mission_id)
        if not future or not record:
            return False
        if future.cancel():
            record.status = "cancelled"
            audit({"event": "mission_cancelled", "id": mission_id})
            return True
        return False

    def _persist(self, record: MissionRecord) -> None:
        try:
            MISSIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
            with MISSIONS_LOG.open("a", encoding="utf-8") as f:
                # Events list can be huge — trim to the last 60 for disk hygiene.
                clone = record.to_dict()
                clone["events"] = clone["events"][-60:]
                f.write(json.dumps(clone, ensure_ascii=False, default=str) + "\n")
        except Exception:
            pass


# Module-level singleton.
pool = MissionPool(max_workers=3)


# ── Public convenience API ───────────────────────────────────────────────────

def submit_mission(goal: str, *, tag: str = "",
                   auto_approve: bool = False,
                   project_slug: str | None = None) -> MissionRecord:
    return pool.submit(goal, tag=tag, auto_approve=auto_approve, project_slug=project_slug)


def list_missions(limit: int = 50) -> list[MissionRecord]:
    return pool.list(limit=limit)


def get_mission(mission_id: str) -> MissionRecord | None:
    return pool.get(mission_id)


def cancel_mission(mission_id: str) -> bool:
    return pool.cancel(mission_id)


def load_persisted_history(limit: int = 100) -> list[dict[str, Any]]:
    if not MISSIONS_LOG.exists():
        return []
    lines = MISSIONS_LOG.read_text(encoding="utf-8").splitlines()[-limit:]
    out: list[dict[str, Any]] = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out
