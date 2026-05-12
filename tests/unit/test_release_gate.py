from __future__ import annotations

from pathlib import Path

from scripts import release_gate


def test_build_steps_runs_qql_before_legacy_gates() -> None:
    report = Path("artifacts/quality/test-release-qql.json")

    steps = release_gate.build_steps(py="python", qql_report=report)

    assert [name for name, _cmd in steps] == ["qql-doctor", "qql", "ruff", "unit", "smoke"]
    assert steps[0][1] == ["python", "scripts/qql.py", "--doctor"]
    assert steps[1][1] == ["python", "scripts/qql.py", "quality", "--report", str(report)]


def test_main_allows_only_smoke_failure(monkeypatch) -> None:
    calls: list[str] = []

    def fake_run(cmd: list[str]) -> int:
        name = {
            "scripts/qql.py": "qql",
            "ruff": "ruff",
            "pytest": "unit",
            "tests.smoke": "smoke",
        }[cmd[1] if cmd[1] in {"scripts/qql.py", "tests.smoke"} else cmd[2]]
        calls.append(name)
        return 1 if name == "smoke" else 0

    monkeypatch.setattr(release_gate, "_run", fake_run)

    rc = release_gate.main(["--allow-smoke-failure"])

    assert rc == 0
    assert calls == ["qql", "qql", "ruff", "unit", "smoke"]


def test_main_does_not_allow_qql_failure(monkeypatch) -> None:
    calls: list[str] = []

    def fake_run(cmd: list[str]) -> int:
        calls.append(cmd[1])
        return 1

    monkeypatch.setattr(release_gate, "_run", fake_run)

    rc = release_gate.main(["--allow-smoke-failure"])

    assert rc == 1
    assert calls == ["scripts/qql.py"]
