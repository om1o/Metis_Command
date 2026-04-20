"""
Metis bootstrap - idempotent first-run setup.

MUST stay stdlib-only - runs BEFORE the venv exists so we can't import
anything outside the standard library.  Every step is safe to re-run.

Public entry point:
    run(tier="Pro", skip_models=False, force_deps=False) -> dict

Steps:
    1. ensure_venv()            create ./metis-env if missing
    2. ensure_deps()            pip install from requirements.txt
    3. ensure_env_file()        copy .env.example -> .env
    4. ensure_dirs()            mkdir -p logs artifacts identity metis_db
    5. ensure_ollama()          detect/start local Ollama (warn only)
    6. ensure_models(tier)      pull required Ollama models silently
    7. mark_setup_done()        write .metis_setup_done stamp
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = ROOT / "metis-env"
STAMP_FILE = ROOT / ".metis_setup_done"
REQ_FILE = ROOT / "requirements.txt"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"

RUNTIME_DIRS = (
    ROOT / "logs",
    ROOT / "artifacts",
    ROOT / "identity",
    ROOT / "metis_db",
)

OLLAMA_BASE = os.getenv("OLLAMA_BASE", "http://localhost:11434")

MODELS_BY_TIER: dict[str, list[str]] = {
    "Lite":      ["qwen2.5-coder:1.5b", "llama3.2:3b"],
    "Pro":       ["qwen2.5-coder:7b", "qwen2.5-coder:1.5b",
                  "deepseek-r1:1.5b", "llama3.2:3b", "qwen3:4b"],
    "Sovereign": ["qwen2.5-coder:7b", "qwen2.5-coder:1.5b",
                  "deepseek-r1:1.5b", "llama3.2:3b", "qwen3:4b",
                  "llava:latest", "glm4:9b"],
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(f"[bootstrap] {msg}", flush=True)


def venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except (urllib.error.URLError, OSError):
        return False


# ── Step 1: venv ────────────────────────────────────────────────────────────

def ensure_venv() -> bool:
    if venv_python().exists():
        log("venv already present.")
        return False
    log(f"creating virtualenv at {VENV_DIR}...")
    builder = venv.EnvBuilder(with_pip=True, upgrade_deps=True)
    builder.create(str(VENV_DIR))
    log("venv created.")
    return True


# ── Step 2: deps ────────────────────────────────────────────────────────────

def ensure_deps(*, force: bool = False) -> bool:
    if not REQ_FILE.exists():
        log("WARN: requirements.txt missing; skipping deps.")
        return False
    py = venv_python()
    if not py.exists():
        raise RuntimeError("venv python missing - run ensure_venv() first")
    if not force and STAMP_FILE.exists() and REQ_FILE.stat().st_mtime <= STAMP_FILE.stat().st_mtime:
        log("deps up-to-date.")
        return False
    log("installing/updating dependencies (this can take a few minutes)...")
    r = subprocess.run(
        [str(py), "-m", "pip", "install", "--disable-pip-version-check",
         "--quiet", "-r", str(REQ_FILE)],
        cwd=str(ROOT),
    )
    if r.returncode != 0:
        raise RuntimeError(f"pip install failed (exit {r.returncode}).")
    log("dependencies installed.")
    return True


# ── Step 3: .env ────────────────────────────────────────────────────────────

def ensure_env_file() -> bool:
    if ENV_FILE.exists():
        return False
    if not ENV_EXAMPLE.exists():
        log("WARN: .env.example missing; cannot bootstrap env.")
        return False
    shutil.copy2(ENV_EXAMPLE, ENV_FILE)
    log(".env created from .env.example (edit to add cloud keys).")
    return True


# ── Step 4: runtime dirs ────────────────────────────────────────────────────

def ensure_dirs() -> list[Path]:
    created: list[Path] = []
    for d in RUNTIME_DIRS:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(d)
    if created:
        log(f"created {len(created)} runtime dir(s).")
    return created


# ── Step 5: Ollama presence ─────────────────────────────────────────────────

def ensure_ollama() -> bool:
    if _http_ok(f"{OLLAMA_BASE}/api/tags"):
        log("Ollama reachable.")
        return True
    for name in ("ollama", "ollama.exe"):
        path = shutil.which(name)
        if path:
            log(f"starting Ollama at {path}...")
            try:
                if platform.system() == "Windows":
                    subprocess.Popen([path, "serve"], creationflags=0x08000000)
                else:
                    subprocess.Popen([path, "serve"])
            except Exception as e:
                log(f"Ollama start failed: {e}")
                return False
            for _ in range(15):
                if _http_ok(f"{OLLAMA_BASE}/api/tags"):
                    log("Ollama up.")
                    return True
                time.sleep(1)
            log("Ollama did not respond within 15s.")
            return False
    log("Ollama not found. Install from https://ollama.com/download then "
        "re-run. Metis will still open; local brains disabled until "
        "Ollama is running.")
    return False


# ── Step 6: model pull ──────────────────────────────────────────────────────

def _ollama_has(model: str) -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
        names = {m.get("name", "") for m in data.get("models", [])}
        return model in names or f"{model}:latest" in names
    except Exception:
        return False


def ensure_models(tier: str = "Pro") -> list[str]:
    if not _http_ok(f"{OLLAMA_BASE}/api/tags"):
        log("Ollama unreachable; skipping model pulls.")
        return []
    models = MODELS_BY_TIER.get(tier) or MODELS_BY_TIER["Pro"]
    pulled: list[str] = []
    for model in models:
        if _ollama_has(model):
            continue
        log(f"pulling {model} (first time - this can take a while)...")
        try:
            req = urllib.request.Request(
                f"{OLLAMA_BASE}/api/pull",
                data=json.dumps({"name": model, "stream": True}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3600) as r:
                last_pct = -1
                for raw in r:
                    try:
                        ev = json.loads(raw.decode("utf-8").strip())
                    except Exception:
                        continue
                    total = ev.get("total") or 0
                    done = ev.get("completed") or 0
                    if total:
                        pct = int(done * 100 / total)
                        if pct != last_pct and pct % 10 == 0:
                            log(f"  {model}: {pct}%")
                            last_pct = pct
                    if ev.get("status") == "success":
                        break
            pulled.append(model)
            log(f"pulled {model}.")
        except Exception as e:
            log(f"pull {model} failed: {e}")
    return pulled


# ── Finalise ────────────────────────────────────────────────────────────────

def mark_setup_done() -> None:
    STAMP_FILE.write_text(
        json.dumps({"ts": int(time.time()), "python": sys.version.split()[0]},
                   indent=2),
        encoding="utf-8",
    )


# ── Public runner ───────────────────────────────────────────────────────────

def run(
    *,
    tier: str = "Pro",
    skip_models: bool = False,
    force_deps: bool = False,
) -> dict:
    report: dict = {"started": time.time()}
    report["venv_created"] = ensure_venv()
    report["deps_installed"] = ensure_deps(force=force_deps)
    report["env_created"] = ensure_env_file()
    report["dirs_created"] = [str(p) for p in ensure_dirs()]
    report["ollama_ready"] = ensure_ollama()
    report["models_pulled"] = [] if skip_models else ensure_models(tier=tier)
    mark_setup_done()
    report["duration_s"] = round(time.time() - report["started"], 1)
    log(f"bootstrap complete in {report['duration_s']}s.")
    return report


# ── CLI ─────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Metis bootstrap")
    p.add_argument("--tier", choices=list(MODELS_BY_TIER.keys()), default="Pro")
    p.add_argument("--skip-models", action="store_true")
    p.add_argument("--force-deps", action="store_true")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    print(json.dumps(
        run(tier=args.tier, skip_models=args.skip_models, force_deps=args.force_deps),
        indent=2,
    ))
