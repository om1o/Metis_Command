"""Run the local release quality gate in a single command."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str]) -> int:
    print(f"[gate] {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=ROOT, check=False)
    return int(proc.returncode)


def main() -> int:
    allow_smoke_failure = "--allow-smoke-failure" in sys.argv[1:]
    py = sys.executable
    # The repo is large and not all legacy modules are fully Ruff-clean yet.
    # Keep this gate actionable by linting the login + UI surface we ship.
    #
    # Note: `dynamic_ui.py` intentionally uses localized imports in a few places
    # to keep optional subsystems best-effort; we ignore PLC0415 for this file.
    ruff_targets = ["dynamic_ui.py", "auth_engine.py", "tool_runtime.py", "ui_theme.py", "launch.py"]
    steps = [
        # Keep linting focused on correctness issues.
        # - Ignore line length (E501) and unused imports (F401) since this file
        #   contains a lot of legacy/optional-path glue code.
        [py, "-m", "ruff", "check", *ruff_targets, "--select", "E,F", "--ignore", "E501,F401"],
        [py, "-m", "pytest", "tests/unit", "-ra", "--tb=short"],
        [py, "-m", "tests.smoke"],
    ]
    for i, cmd in enumerate(steps):
        rc = _run(cmd)
        if i == 2 and allow_smoke_failure and rc != 0:
            print("[gate] smoke failed but allowed by flag")
            return 0
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
