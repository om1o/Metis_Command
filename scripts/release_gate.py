"""Run the local release quality gate in a single command."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).absolute().parent.parent
DEFAULT_QQL_REPORT = ROOT / "artifacts" / "quality" / "release-gate-qql.json"


def _run(cmd: list[str]) -> int:
    print(f"[gate] {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=ROOT, check=False)
    return int(proc.returncode)


def build_steps(*, py: str, qql_report: Path) -> list[tuple[str, list[str]]]:
    # The repo is large and not all legacy modules are fully Ruff-clean yet.
    # Keep this gate actionable by linting the login + UI surface we ship.
    #
    # Note: `dynamic_ui.py` intentionally uses localized imports in a few places
    # to keep optional subsystems best-effort; we ignore PLC0415 for this file.
    ruff_targets = ["dynamic_ui.py", "auth_engine.py", "tool_runtime.py", "ui_theme.py", "launch.py"]
    return [
        (
            "qql-doctor",
            [py, "scripts/qql.py", "--doctor"],
        ),
        (
            "qql",
            [py, "scripts/qql.py", "quality", "--report", str(qql_report)],
        ),
        # Keep linting focused on correctness issues.
        # - Ignore line length (E501) and unused imports (F401) since this file
        #   contains a lot of legacy/optional-path glue code.
        (
            "ruff",
            [py, "-m", "ruff", "check", *ruff_targets, "--select", "E,F", "--ignore", "E501,F401"],
        ),
        ("unit", [py, "-m", "pytest", "tests/unit", "-ra", "--tb=short"]),
        ("smoke", [py, "-m", "tests.smoke"]),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Metis release quality gates.")
    parser.add_argument("--allow-smoke-failure", action="store_true", help="allow the legacy smoke gate to fail")
    parser.add_argument(
        "--qql-report",
        type=Path,
        default=DEFAULT_QQL_REPORT,
        help="where to write the QQL quality report",
    )
    args = parser.parse_args(argv)

    for name, cmd in build_steps(py=sys.executable, qql_report=args.qql_report):
        rc = _run(cmd)
        if name == "smoke" and args.allow_smoke_failure and rc != 0:
            print("[gate] smoke failed but allowed by flag")
            return 0
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
