"""
Module Manager — silent tier downloads for Lite / Standard / Sovereign.

Closes the marketing promise: the user picks a tier during onboarding,
this module silently pulls the matching Ollama models in the background
while they finish setting up their account. Never shows gigabyte numbers
in the UI (pass a percent callback instead).
"""

from __future__ import annotations

import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import psutil

from brain_engine import ensure_model, list_local_models

# Size is approximate disk footprint (GB) — used only for free-space checks.
TIER_MANIFEST: dict[str, list[tuple[str, float]]] = {
    "Lite": [
        ("qwen2.5-coder:1.5b", 1.0),
        ("qwen3.5:4b",         3.4),
        ("llama3.2:3b",        2.0),
        ("deepseek-r1:1.5b",   1.1),
    ],
    "Standard": [
        ("qwen2.5-coder:1.5b", 1.0),
        ("qwen2.5-coder:7b",   4.7),
        ("qwen3.5:4b",         3.4),
        ("llama3.2:3b",        2.0),
        ("deepseek-r1:1.5b",   1.1),
        ("llava:latest",       4.7),
    ],
    "Sovereign": [
        ("qwen2.5-coder:1.5b", 1.0),
        ("qwen2.5-coder:7b",   4.7),
        ("qwen3.5:4b",         3.4),
        ("llama3.2:3b",        2.0),
        ("deepseek-r1:1.5b",   1.1),
        ("llava:latest",       4.7),
        # Heavier Sovereign-only models; safe to fail — user can retry later.
        ("deepseek-r1:8b",     5.2),
        ("qwen2.5-coder:14b",  8.9),
    ],
}

# Safety margin: never start a pull if free disk would drop below this (GB).
MIN_FREE_GB = 5.0


@dataclass
class TierPlan:
    tier: str
    models: list[str]
    missing: list[str]
    present: list[str]
    total_gb: float
    missing_gb: float


class ModuleManager:
    """Singleton-style background downloader with pause/resume/abort."""

    def __init__(self) -> None:
        self._pause = threading.Event()
        self._abort = threading.Event()
        self._thread: threading.Thread | None = None
        self._current_model: str | None = None
        self._progress: dict[str, float] = {}  # model -> 0.0..1.0

    # ── planning ─────────────────────────────────────────────────────────────
    def plan_tier(self, tier: str) -> TierPlan:
        if tier not in TIER_MANIFEST:
            raise ValueError(f"Unknown tier: {tier}")
        entries = TIER_MANIFEST[tier]
        local = set(list_local_models())
        models = [m for m, _ in entries]
        missing = [m for m, _ in entries if m not in local]
        present = [m for m in models if m in local]
        total_gb = sum(gb for _, gb in entries)
        missing_gb = sum(gb for m, gb in entries if m in missing)
        return TierPlan(
            tier=tier,
            models=models,
            missing=missing,
            present=present,
            total_gb=total_gb,
            missing_gb=missing_gb,
        )

    # ── control surface ──────────────────────────────────────────────────────
    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    def abort(self) -> None:
        self._abort.set()
        self._pause.clear()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def current_model(self) -> str | None:
        return self._current_model

    @property
    def progress_snapshot(self) -> dict[str, float]:
        return dict(self._progress)

    # ── disk guard ───────────────────────────────────────────────────────────
    def _disk_ok(self, needed_gb: float, root: str | Path = ".") -> bool:
        free_bytes = shutil.disk_usage(str(Path(root).resolve())).free
        free_gb = free_bytes / (1024 ** 3)
        return (free_gb - needed_gb) >= MIN_FREE_GB

    # ── download ─────────────────────────────────────────────────────────────
    def download_tier_silent(
        self,
        tier: str,
        on_progress: Callable[[dict], None] | None = None,
    ) -> threading.Thread:
        """Kick off a background download. Returns the worker thread."""
        if self.is_running:
            raise RuntimeError("A tier download is already running.")
        self._abort.clear()
        self._pause.clear()
        plan = self.plan_tier(tier)

        if not self._disk_ok(plan.missing_gb):
            if on_progress:
                on_progress({"type": "error", "reason": "low-disk"})
            raise RuntimeError("Not enough free disk for this tier.")

        def worker() -> None:
            for model, _ in TIER_MANIFEST[tier]:
                if self._abort.is_set():
                    break
                if model in plan.present:
                    self._progress[model] = 1.0
                    if on_progress:
                        on_progress({"type": "skipped", "model": model})
                    continue

                while self._pause.is_set() and not self._abort.is_set():
                    time.sleep(0.5)
                if self._abort.is_set():
                    break

                self._current_model = model
                self._progress[model] = 0.0
                if on_progress:
                    on_progress({"type": "start", "model": model})

                def on_chunk(ev: dict) -> None:
                    total = ev.get("total") or 0
                    completed = ev.get("completed") or 0
                    if total:
                        self._progress[model] = min(1.0, completed / total)
                    if on_progress:
                        on_progress({
                            "type": "progress",
                            "model": model,
                            "percent": round(self._progress[model] * 100, 1),
                            "status": ev.get("status", ""),
                        })

                ok = ensure_model(model, on_progress=on_chunk)
                self._progress[model] = 1.0 if ok else self._progress.get(model, 0.0)
                if on_progress:
                    on_progress({
                        "type": "done" if ok else "failed",
                        "model": model,
                    })

            self._current_model = None
            if on_progress:
                on_progress({"type": "all-done"})

        self._thread = threading.Thread(target=worker, daemon=True, name="MetisTierDL")
        self._thread.start()
        return self._thread


# Module-level singleton for easy import across the app.
manager = ModuleManager()


def plan_tier(tier: str) -> TierPlan:
    return manager.plan_tier(tier)


def download_tier_silent(tier: str, on_progress=None) -> threading.Thread:
    return manager.download_tier_silent(tier, on_progress=on_progress)
