from __future__ import annotations

from scripts import ai_smoke_gate


def test_selected_checks_includes_manager_only_when_requested() -> None:
    assert [name for name, _check in ai_smoke_gate.selected_checks(manager_chat=False)] == [
        "system_health",
        "direct_chat",
        "autonomous_exact_answers",
    ]
    assert [name for name, _check in ai_smoke_gate.selected_checks(manager_chat=True)] == [
        "system_health",
        "direct_chat",
        "manager_chat",
        "autonomous_exact_answers",
    ]


def test_selected_checks_includes_direct_chat_load_before_manager() -> None:
    assert [name for name, _check in ai_smoke_gate.selected_checks(manager_chat=True, direct_chat_repeats=3)] == [
        "system_health",
        "direct_chat",
        "direct_chat_load_3",
        "manager_chat",
        "autonomous_exact_answers",
    ]


def test_run_gate_stops_after_first_failure() -> None:
    calls: list[str] = []

    def ok() -> None:
        calls.append("ok")

    def fail() -> None:
        calls.append("fail")
        raise AssertionError("broken ai path")

    def skipped() -> None:
        calls.append("skipped")

    results, duration_s = ai_smoke_gate.run_gate([
        ("first", ok),
        ("second", fail),
        ("third", skipped),
    ])

    assert calls == ["ok", "fail"]
    assert duration_s >= 0
    assert results[0]["status"] == "ok"
    assert results[1]["name"] == "second"
    assert results[1]["status"] == "failed"
    assert results[1]["error"] == "broken ai path"


def test_build_report_marks_failed_result_not_ok() -> None:
    report = ai_smoke_gate.build_report(
        manager_chat=True,
        direct_chat_repeats=3,
        duration_s=1.25,
        results=[{"name": "direct_chat", "status": "failed", "duration_s": 0.2, "error": "bad"}],
    )

    assert report["schema"] == "metis.ai_smoke.report.v1"
    assert report["ok"] is False
    assert report["manager_chat"] is True
    assert report["direct_chat_repeats"] == 3
    assert report["duration_s"] == 1.25
    assert report["results"] == [{"name": "direct_chat", "status": "failed", "duration_s": 0.2, "error": "bad"}]


def test_write_report_creates_json_file(tmp_path) -> None:
    report_path = tmp_path / "ai" / "smoke.json"

    ai_smoke_gate.write_report(report_path, {"schema": "metis.ai_smoke.report.v1", "ok": True})

    assert report_path.read_text(encoding="utf-8") == '{\n  "schema": "metis.ai_smoke.report.v1",\n  "ok": true\n}\n'
