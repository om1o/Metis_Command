"""
Quick smoke-test for Groq + GLM. Run after setting GROQ_API_KEY and GLM_API_KEY.

  python scripts/test_cloud_providers.py
"""
import sys, time
sys.path.insert(0, '.')

try:
    from dotenv import load_dotenv
    from pathlib import Path as _P
    # Try every .env we know about — worktree first (most local),
    # then parent repo, then the sibling Metis_Command.
    for _p in [
        _P('.env'),
        _P('../../../.env'),  # from .claude/worktrees/<wt>/
        _P('../../../Metis_Command/.env'),
    ]:
        if _p.exists():
            load_dotenv(str(_p), override=False)
except Exception:
    pass

from providers import groq as _groq, glm as _glm

QUESTIONS = [
    "What is the capital of Japan? One word.",
    "What is 7 x 8? One number.",
    "Name one programming language invented before 1980. One word.",
]

def test_provider(name: str, mod, questions: list[str]) -> bool:
    print(f"\n{'='*50}")
    print(f"  {name}")
    print(f"{'='*50}")
    if not mod.is_configured():
        print(f"  [FAIL] NOT CONFIGURED — set {name.upper()}_API_KEY in .env")
        return False
    print(f"  [ OK ] key set: {mod.api_key()[:12]}...")
    print(f"  model: {mod.default_model()}")
    ok = True
    for q in questions:
        t0 = time.time()
        try:
            ans = mod.chat([{"role": "user", "content": q}])
            dur = time.time() - t0
            if ans.startswith("["):  # error prefix
                print(f"  [FAIL] Q: {q!r}\n    A: {ans}")
                ok = False
            else:
                print(f"  [ OK ] Q: {q!r}\n    A: {ans.strip()!r}  ({dur:.2f}s)")
        except Exception as e:
            print(f"  [FAIL] Q: {q!r}\n    ERROR: {e}")
            ok = False
    return ok

groq_ok = test_provider("GROQ", _groq, QUESTIONS)
glm_ok  = test_provider("GLM",  _glm,  QUESTIONS)

print(f"\n{'='*50}")
print(f"  GROQ: {'PASS' if groq_ok else 'FAIL (not configured or error)'}")
print(f"  GLM:  {'PASS' if glm_ok  else 'FAIL (not configured or error)'}")
print(f"{'='*50}\n")

sys.exit(0 if (groq_ok and glm_ok) else 1)
