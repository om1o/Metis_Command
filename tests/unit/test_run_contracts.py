"""Run-mode and permission contracts."""

from __future__ import annotations


def test_run_contract_normalizes_mode_and_permission():
    from run_contracts import build_run_contract

    wrapped = build_run_contract("Check my stocks.", mode="JOB", permission="READ")

    assert "Mode: Job" in wrapped
    assert "Permission: Read-only" in wrapped
    assert wrapped.endswith("Check my stocks.")


def test_run_contract_falls_back_to_safe_defaults():
    from run_contracts import build_run_contract

    wrapped = build_run_contract("Do it.", mode="trade-all", permission="root")

    assert "Mode: Task" in wrapped
    assert "Permission: Balanced" in wrapped
    assert wrapped.endswith("Do it.")


def test_scheduler_persists_job_contract_metadata(_sandbox_paths):
    import scheduler

    sched = scheduler.add(
        "Summarize market news.",
        kind="daily",
        spec="09:00",
        mode="job",
        permission="read",
    )

    assert sched.mode == "job"
    assert sched.permission == "read"
    persisted = scheduler.list_schedules()[0].to_dict()
    assert persisted["mode"] == "job"
    assert persisted["permission"] == "read"
