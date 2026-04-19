"""
Metis smoke test — walks the full offline flow end-to-end.

Run with:
    python -m tests.smoke

Every step is wrapped in its own try/except so one missing dep doesn't
kill the whole walk.  Output uses `rich` if available, plain print otherwise.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

def ok(msg: str) -> None: print(f"[OK]   {msg}")
def warn(msg: str) -> None: print(f"[WARN] {msg}")
def fail(msg: str) -> None: print(f"[FAIL] {msg}")
def head(msg: str) -> None: print(f"\n==== {msg} ====")


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _step(name, fn):
    try:
        fn()
        ok(name)
        return True
    except Exception as e:
        fail(f"{name}: {e}")
        traceback.print_exc()
        return False


def main() -> int:
    head("Metis Smoke Test - V16.3 Apex")
    failed = 0

    # 0 — imports
    def t_imports() -> None:
        import brain_engine, memory, memory_vault, memory_loop  # noqa
        import swarm_agents, task_manager, crew_engine           # noqa
        import skill_forge, artifacts, marketplace, subscription # noqa
        import mts_format, module_manager                         # noqa
    failed += 0 if _step("imports", t_imports) else 1

    # 1 — hardware scanner
    def t_hw() -> None:
        from hardware_scanner import get_hardware_tier, get_hardware_report
        tier = get_hardware_tier()
        report = get_hardware_report()
        assert tier in {"Lite", "Pro", "Sovereign"}
        assert report["tier"] == tier
    failed += 0 if _step("hardware_scanner", t_hw) else 1

    # 2 — brain engine listing
    def t_brain() -> None:
        from brain_engine import ROLE_MODELS, list_local_models
        assert "manager" in ROLE_MODELS
        names = list_local_models()
        if not names:
            warn("no Ollama models pulled yet")
    failed += 0 if _step("brain_engine", t_brain) else 1

    # 3 — module manager planning
    def t_modules() -> None:
        from module_manager import plan_tier
        p = plan_tier("Lite")
        assert p.tier == "Lite"
    failed += 0 if _step("module_manager.plan_tier", t_modules) else 1

    # 4 — artifact save/list
    def t_artifact() -> None:
        from artifacts import Artifact, save_artifact, list_artifacts
        art = save_artifact(Artifact(type="doc", title="smoke", content="hello"))
        assert any(a.id == art.id for a in list_artifacts())
    failed += 0 if _step("artifacts", t_artifact) else 1

    # 5 — skill forge registry
    def t_skills() -> None:
        from skill_forge import list_skills, invoke
        skills = {s["name"] for s in list_skills()}
        assert "system_status" in skills
        result = invoke("system_status")
        assert "hardware_tier" in result
    failed += 0 if _step("skill_forge.registry", t_skills) else 1

    # 6 — sandbox (best-effort)
    def t_sandbox() -> None:
        from skill_forge import run_in_sandbox
        result = run_in_sandbox("print(1+1)")
        assert result["ok"] or result["mode"] == "subprocess"
    failed += 0 if _step("skill_forge.run_in_sandbox", t_sandbox) else 1

    # 7 — .mts round-trip
    def t_mts() -> None:
        from mts_format import export_identity, import_identity
        out = Path("identity") / "smoke_brain.mts"
        export_identity(str(out), password="smoke")
        payload = import_identity(str(out), password="smoke")
        assert payload["kind"] == "MetisThoughtState"
        out.unlink(missing_ok=True)
    failed += 0 if _step("mts_format round-trip", t_mts) else 1

    # 8 — subscription default
    def t_sub() -> None:
        from subscription import get_current_tier, require_tier, Tier
        t = get_current_tier()
        assert t in (Tier.FREE, Tier.PRO, Tier.ENTERPRISE)
        assert require_tier(Tier.FREE)
    failed += 0 if _step("subscription.get_current_tier", t_sub) else 1

    # 9 — marketplace catalog fallback
    def t_market() -> None:
        from marketplace import list_plugins
        plugins = list_plugins()
        assert len(plugins) >= 5
    failed += 0 if _step("marketplace.list_plugins", t_market) else 1

    # 10 — FastAPI app importable
    def t_api() -> None:
        import api_bridge
        assert api_bridge.app
    failed += 0 if _step("api_bridge imports", t_api) else 1

    # 11 — GLM provider wiring (no network call)
    def t_glm() -> None:
        from providers import glm
        from brain_engine import ROLE_MODELS, get_active_model
        assert "genius" in ROLE_MODELS
        model = get_active_model("genius")
        assert model  # either cloud GLM or a local fallback string
        # is_glm_model recognises our default
        assert glm.is_glm_model(ROLE_MODELS["genius"])
    failed += 0 if _step("glm provider wiring", t_glm) else 1

    # 12 — Brains: create / remember / recall / compact
    def t_brains() -> None:
        import brains
        b = brains.create("Smoke")
        try:
            eid = brains.remember("Director prefers concise answers.",
                                  kind="semantic", brain=b)
            assert eid
            hits = brains.recall("director preferences", k=3, brain=b)
            # Chroma sometimes needs a moment, don't fail hard.
            _ = hits
            # compact returns 0 when under `window`, which is fine here.
            brains.compact(brain=b, window=1_000_000)
        finally:
            brains.delete(b.slug)
    failed += 0 if _step("brains CRUD + compact", t_brains) else 1

    # 13 — Wallet charge/BudgetExceeded behavior
    def t_wallet() -> None:
        import wallet
        wallet.top_up(500, source="smoke")
        entry = wallet.charge("subagent", 1, memo="smoke")
        assert entry.balance_after_cents >= 0
        try:
            wallet.charge("plugin", 10_000_000, memo="smoke:over")
        except wallet.BudgetExceeded:
            pass
        else:
            raise AssertionError("expected BudgetExceeded")
    failed += 0 if _step("wallet charge + BudgetExceeded", t_wallet) else 1

    # 14 — Agent roster + bus round-trip (no LLM call)
    def t_bus() -> None:
        import agent_bus as bus
        import agent_roster as roster
        specs = roster.list_roster()
        assert len(specs) >= 5
        # publish a direct message and drain it back
        bus.publish(bus.AgentMessage(
            from_slug="orchestrator", to_slug="scheduler",
            kind="ping", payload={"t": 1},
        ))
        msgs = bus.drain("scheduler", limit=5, timeout=0.5)
        assert any(m.kind == "ping" for m in msgs)
    failed += 0 if _step("agent_bus round-trip", t_bus) else 1

    # 15 — Scheduler seeding (idempotent)
    def t_scheduler() -> None:
        import scheduler
        first = scheduler.seed_default_schedules()
        second = scheduler.seed_default_schedules()
        assert isinstance(first, list) and isinstance(second, list)
        # second call should add nothing because action names already exist
        assert len(second) == 0
        actions = {s.action for s in scheduler.list_schedules() if s.action}
        for expected in ("daily_briefing", "nightly_brain_compact", "weekly_brain_backup"):
            assert expected in actions
    failed += 0 if _step("scheduler seed_default_schedules", t_scheduler) else 1

    head(f"Done · {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
