"""Shared run-mode and permission contracts for chat and scheduled jobs."""

from __future__ import annotations

RUN_MODES = {"task", "job"}
PERMISSIONS = {"read", "balanced", "full"}

PERMISSION_CONTRACTS = {
    "read": (
        "Permission: Read-only. Gather information, inspect local state, and draft a plan. "
        "Do not make file, system, browser, account, purchase, or external communication changes."
    ),
    "balanced": (
        "Permission: Balanced. You may make reversible local workspace changes and use safe tools. "
        "Ask before spending money, changing credentials, contacting people, trading, deleting data, "
        "or taking irreversible actions."
    ),
    "full": (
        "Permission: Full local execution. You may edit files, run tools, and complete the task, "
        "but still ask before financial trades, legal/medical decisions, credentials, external messages, "
        "or destructive changes."
    ),
}

MODE_CONTRACTS = {
    "task": "Mode: Task. Run this once now, report progress, and finish with the result.",
    "job": (
        "Mode: Job. This is a scheduled recurring task. Run only the current occurrence, "
        "record useful results, and report back to the manager."
    ),
}


def normalize_mode(value: str | None) -> str:
    value = (value or "task").strip().lower()
    return value if value in RUN_MODES else "task"


def normalize_permission(value: str | None) -> str:
    value = (value or "balanced").strip().lower()
    return value if value in PERMISSIONS else "balanced"


def build_run_contract(message: str, *, mode: str | None = "task", permission: str | None = "balanced") -> str:
    """Attach the operator contract while keeping the user's visible text unchanged."""
    run_mode = normalize_mode(mode)
    perm = normalize_permission(permission)
    return (
        "[Metis run contract]\n"
        f"{MODE_CONTRACTS[run_mode]}\n"
        f"{PERMISSION_CONTRACTS[perm]}\n"
        "[/Metis run contract]\n\n"
        f"{message.strip()}"
    )
