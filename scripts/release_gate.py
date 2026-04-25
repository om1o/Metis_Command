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
    steps = [
        ["python", "-m", "ruff", "check", "."],
        ["python", "-m", "pytest", "tests/unit", "-ra", "--tb=short"],
        ["python", "-m", "tests.smoke"],
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
