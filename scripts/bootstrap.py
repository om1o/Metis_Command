"""
Stdlib-only first-run setup for Metis Command.

Handles: venv creation, dependency installation, Ollama model pulls.
Must import with stdlib only — runs before the venv exists.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = ROOT / ".venv"
STAMP_FILE = ROOT / ".metis_setup_done"
REQS_FILE = ROOT / "requirements.txt"


def venv_python() -> Path:
    """Return the path to the Python executable inside the venv."""
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _create_venv() -> None:
    if VENV_DIR.exists():
        return
    print(f"[bootstrap] creating venv at {VENV_DIR}", flush=True)
    subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
    print("[bootstrap] venv created.", flush=True)


def _install_deps(force: bool = False) -> None:
    py = venv_python()
    if not py.exists():
        print("[bootstrap] venv python not found — skipping dep install", flush=True)
        return
    if not REQS_FILE.exists():
        print("[bootstrap] requirements.txt not found — skipping dep install", flush=True)
        return
    if not force and STAMP_FILE.exists():
        return  # already done
    print("[bootstrap] installing dependencies (first run takes a few minutes)…", flush=True)
    subprocess.check_call(
        [str(py), "-m", "pip", "install", "-r", str(REQS_FILE), "--quiet"],
    )
    print("[bootstrap] dependencies installed.", flush=True)


def _write_stamp(tier: str) -> None:
    import time
    data = {
        "ts": int(time.time()),
        "python": sys.version.split()[0],
        "tier": tier,
    }
    STAMP_FILE.write_text(json.dumps(data, indent=2))


def _pull_models(tier: str) -> None:
    """Pull Ollama models for the selected tier — best-effort."""
    try:
        py = venv_python()
        subprocess.check_call(
            [str(py), "-c",
             f"from module_manager import pull_tier; pull_tier('{tier}')"],
            cwd=str(ROOT),
        )
    except Exception as e:
        print(f"[bootstrap] model pull skipped: {e}", flush=True)


def run(
    tier: str = "Pro",
    skip_models: bool = False,
    force_deps: bool = False,
) -> None:
    """Run the full bootstrap sequence."""
    _create_venv()
    _install_deps(force=force_deps)
    _write_stamp(tier)
    if not skip_models:
        _pull_models(tier)
