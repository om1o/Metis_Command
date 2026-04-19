"""
Build the Metis Command release ZIP.

Output:
    dist/metis-command-windows.zip

Contents:
    Everything needed to run `metis.bat` (or `python launch.py`) on a fresh
    Windows box: all .py source files at the repo root, providers/, tools/,
    plugins/, scripts/, modelfiles/, .env.example, README.md,
    requirements.txt, launch.py, metis.bat.

Excluded (see EXCLUDE_NAMES / EXCLUDE_FILE_GLOBS below):
    metis-env/, logs/, artifacts/, identity/, metis_db/, __pycache__/, .git/,
    site/, dist/, anything resembling secrets or user data.

Also writes dist/VERSION.txt and dist/SHA256.txt next to the ZIP.

Usage:
    python scripts/package_metis.py
    python scripts/package_metis.py --version 0.17.0
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"

INCLUDE_DIRS = (
    "providers", "tools", "plugins", "scripts", "modelfiles", "tests",
    "docs", "animations", "modules",
)
INCLUDE_FILES = (
    "*.py", "*.spec", "*.sql", "*.md", "*.bat", "*.ps1", "*.cmd",
    "*.txt", "*.in", "*.example", ".gitignore",
    "requirements.txt", "requirements-dev.txt",
    "requirements.in", "requirements-dev.in",
    "launch.py", "start_metis.pyw",
)
EXCLUDE_NAMES = {
    ".git", "metis-env", "venv", ".venv",
    "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache",
    "logs", "artifacts", "identity", "metis_db", "dist", "build",
    "node_modules", "site",
}
EXCLUDE_FILE_GLOBS = (
    "*.pyc", "*.pyo", "*.log",
    ".env", ".env.local", "*.mts",
    "local_auth.token", "wallet.json", "schedules.json",
    "persistent_agents.json", "user_matrix.json",
    "compile.log",
)


def _included(path: Path) -> bool:
    for part in path.parts:
        if part in EXCLUDE_NAMES:
            return False
    name = path.name
    for pat in EXCLUDE_FILE_GLOBS:
        if fnmatch.fnmatch(name, pat):
            return False
    if path.is_file():
        if path.parent == ROOT:
            return any(fnmatch.fnmatch(name, pat) for pat in INCLUDE_FILES)
        top = path.relative_to(ROOT).parts[0]
        return top in INCLUDE_DIRS
    return True


def _gather() -> list[Path]:
    picked: list[Path] = []
    for p in ROOT.rglob("*"):
        if p.is_dir():
            continue
        if _included(p):
            picked.append(p)
    return picked


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="Package Metis Command release")
    p.add_argument("--version", default="0.16.4")
    p.add_argument("--name",    default="metis-command-windows")
    args = p.parse_args(argv)

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True, exist_ok=True)

    zip_path = DIST / f"{args.name}.zip"
    files = _gather()
    if not files:
        print("nothing to package", file=sys.stderr)
        return 1

    print(f"[package] {len(files)} files -> {zip_path}")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for fp in files:
            arc = Path("Metis_Command") / fp.relative_to(ROOT)
            z.write(fp, arcname=str(arc))

    digest = _sha256(zip_path)
    (DIST / "VERSION.txt").write_text(args.version + "\n", encoding="utf-8")
    (DIST / "SHA256.txt").write_text(
        f"{digest}  {zip_path.name}\n", encoding="utf-8"
    )

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(
        f"[package] done  version={args.version}  "
        f"size={size_mb:.1f} MB  sha256={digest[:16]}..."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
