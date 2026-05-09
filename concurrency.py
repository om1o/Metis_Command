"""
Mission Concurrency Pool — Manus-style parallel autonomous tasks.

Lets the Director fire-and-forget N missions that run in parallel, with
live status polling from the UI ("Mission #3 · step 4/10 · Coder active").
Each submission is tracked in-memory by id; persistent history lives in
`logs/missions.jsonl` for replay and the `/replay <id>` command.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from safety import PATHS, audit
from artifacts import Artifact, save_artifact


MISSIONS_LOG = PATHS.logs / "missions.jsonl"


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


class PoolFull(Exception):
    """Raised when the mission queue is at capacity."""


class MissionPool:
    """
    Thread-pool runner for autonomous-loop missions.

    Bounded on two axes so runaway callers can't DoS the local brain:
      * `max_workers`        - concurrent missions actually running
      * `max_queue_depth`    - queued + running mission cap; beyond this
                                `submit()` raises `PoolFull`

    Both defaults come from env so ops can tune without editing code.
    """

    def __init__(
        self,
        max_workers: int | None = None,
        *,
        max_queue_depth: int | None = None,
    ) -> None:
        mw = max_workers or int(os.getenv("METIS_MAX_WORKERS", "3") or "3")
        qd = max_queue_depth or int(os.getenv("METIS_MAX_QUEUE", "24") or "24")
        self._max_workers = max(1, mw)
        self._max_queue_depth = max(self._max_workers, qd)
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="MetisMission",
        )
        self._semaphore = threading.BoundedSemaphore(self._max_workers)
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
        with self._lock:
            inflight = sum(
                1 for r in self._records.values()
                if r.status in ("queued", "running")
            )
        if inflight >= self._max_queue_depth:
            audit({
                "event": "mission_rejected_full",
                "inflight": inflight,
                "max_queue": self._max_queue_depth,
                "goal": goal[:120],
            })
            raise PoolFull(
                f"mission queue full ({inflight}/{self._max_queue_depth}); "
                "retry later or bump METIS_MAX_QUEUE."
            )
        record = MissionRecord(
            goal=goal,
            tag=tag,
            project_slug=project_slug,
            auto_approve=auto_approve,
        )
        with self._lock:
            self._records[record.id] = record
        from autonomous_loop import run_mission as mission_runner

        def run() -> None:
            # Semaphore gate - serialises beyond max_workers even when tasks
            # spawn other tasks internally.
            with self._semaphore:
                with self._lock:
                    record.status = "running"
                    record.started_at = time.time()
                try:
                    on_event = record.events.append
                    mission = mission_runner(
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
                    audit({"event": "mission_worker_error",
                           "id": record.id, "error": str(e)})
                finally:
                    with self._lock:
                        record.ended_at = time.time()
                    self._save_scheduled_report(record)
                    self._persist(record)

        future = self._executor.submit(run)
        with self._lock:
            self._futures[record.id] = future
        audit({"event": "mission_submitted",
               "id": record.id, "goal": goal[:120], "tag": tag,
               "inflight": inflight + 1,
               "max_queue": self._max_queue_depth})
        return record

    # ── bookkeeping helpers ────────────────────────────────────────────────
    def stats(self) -> dict:
        with self._lock:
            by_status: dict[str, int] = {}
            for r in self._records.values():
                by_status[r.status] = by_status.get(r.status, 0) + 1
        return {
            "max_workers":      self._max_workers,
            "max_queue_depth":  self._max_queue_depth,
            "by_status":        by_status,
            "total_records":    len(self._records),
        }

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

    def _save_scheduled_report(self, record: MissionRecord) -> None:
        if not record.tag.startswith("scheduled:"):
            return
        schedule_id = record.tag.split(":", 1)[1].strip()
        duration_ms = int(((record.ended_at or time.time()) - (record.started_at or record.submitted_at)) * 1000)
        first_line = record.goal.splitlines()[0][:80] or schedule_id
        event_lines = []
        for event in record.events[-20:]:
            event_type = event.get("type", "event")
            detail = event.get("description") or event.get("answer") or event.get("error") or event.get("status") or ""
            event_lines.append(f"- `{event_type}` {str(detail)[:240]}".rstrip())
        content = "\n".join([
            f"# Scheduled Job Report: {first_line}",
            "",
            f"- Mission: `{record.id}`",
            f"- Schedule: `{schedule_id}`",
            f"- Status: `{record.status}`",
            f"- Duration: `{duration_ms} ms`",
            "",
            "## Goal",
            record.goal.strip(),
            "",
            "## Result",
            record.final_answer.strip() or "No final answer was produced.",
            "",
            "## Run Events",
            "\n".join(event_lines) if event_lines else "No run events were recorded.",
            "",
        ])
        try:
            artifact = save_artifact(Artifact(
                type="doc",
                title=f"Scheduled job: {first_line}",
                language="markdown",
                content=content,
                metadata={
                    "kind": "scheduled_job_report",
                    "mission_id": record.id,
                    "schedule_id": schedule_id,
                    "status": record.status,
                    "tag": record.tag,
                },
            ))
            audit({
                "event": "scheduled_job_report_saved",
                "mission_id": record.id,
                "schedule_id": schedule_id,
                "artifact_id": artifact.id,
            })
            try:
                import inbox as _inbox
                _inbox.append(
                    title=f"Job report saved - {first_line}",
                    body=f"Scheduled job finished with status `{record.status}`.\n\nReport: {artifact.title}",
                    source=record.tag,
                    schedule_id=schedule_id,
                    artifact_id=artifact.id,
                )
            except Exception:
                pass
        except Exception as e:
            audit({
                "event": "scheduled_job_report_failed",
                "mission_id": record.id,
                "schedule_id": schedule_id,
                "error": str(e),
            })


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
