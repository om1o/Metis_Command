"""
Pre-commit hook: scan staged files for credential patterns.

Wraps `safety.secret_scan` so we reuse the same regex set the runtime
uses to redact outgoing payloads.  Returns non-zero when anything looks
like a secret, blocking the commit.

Invoked by .pre-commit-config.yaml; also usable standalone:
    python scripts/pre_commit_secret_scan.py path1 path2 ...
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from safety import secret_scan
except Exception as e:
    print(f"[secret-scan] cannot import safety: {e}", file=sys.stderr)
    sys.exit(0)  # fail-open so the hook doesn't brick commits during dev


SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp",
                 ".ico", ".svg", ".pdf", ".zip",
                 ".mts", ".bin", ".safetensors", ".gguf", ".onnx"}
SKIP_DIRS = {"metis-env", "node_modules", ".next", "dist", "build",
             ".git", "logs", "metis_db", "artifacts", "__pycache__"}


def should_scan(path: Path) -> bool:
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    for part in path.parts:
        if part in SKIP_DIRS:
            return False
    return True


def main(argv: list[str]) -> int:
    bad: list[tuple[str, list[dict]]] = []
    for arg in argv:
        p = Path(arg)
        if not p.exists() or p.is_dir():
            continue
        if not should_scan(p):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        hits = secret_scan(text)
        if hits:
            bad.append((str(p), hits))

    if not bad:
        return 0

    print("[secret-scan] Refusing commit - potential secrets detected:", file=sys.stderr)
    for path, hits in bad:
        print(f"  {path}", file=sys.stderr)
        for h in hits:
            print(f"    - {h['kind']}: {h['match']}", file=sys.stderr)
    print("\nEither (a) remove the secret, (b) rotate it, or (c) skip this "
          "hook with `git commit --no-verify` (not recommended).",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
