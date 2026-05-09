from __future__ import annotations

import os

import pytest

from scripts import qql


def test_parse_quality_alias_expands_in_order() -> None:
    checks = qql.parse_query("quality")

    assert [check.key for check in checks] == ["quality.diff", "tests.qql", "tests.backend"]


def test_parse_query_accepts_spaces_commas_and_plus_signs() -> None:
    checks = qql.parse_query("ai.basic, quality + ui")

    assert [check.key for check in checks] == [
        "ai.basic",
        "quality.diff",
        "tests.qql",
        "tests.backend",
        "ui.desktop.lint",
        "ui.desktop.build",
    ]


def test_parse_query_dedupes_repeated_selectors() -> None:
    checks = qql.parse_query("ai ai.basic ai")

    assert [check.key for check in checks] == ["ai.basic"]


def test_parse_load_alias_selects_ai_load() -> None:
    checks = qql.parse_query("load")

    assert [check.key for check in checks] == ["ai.load"]
    assert "--direct-chat-repeats" in checks[0].command
    assert "--manager-chat" in checks[0].command


def test_parse_build_alias_selects_desktop_lint_and_build() -> None:
    checks = qql.parse_query("build")

    assert [check.key for check in checks] == ["ui.desktop.lint", "ui.desktop.build"]


def test_parse_e2e_alias_uses_ai_load_not_basic() -> None:
    checks = qql.parse_query("e2e")

    assert [check.key for check in checks] == [
        "quality.diff",
        "tests.qql",
        "tests.backend",
        "ui.desktop.lint",
        "ui.desktop.build",
        "ai.load",
    ]


def test_parse_all_uses_ai_load_gate() -> None:
    checks = qql.parse_query("all")

    assert [check.key for check in checks][-1] == "ai.load"
    assert "ai.basic" not in [check.key for check in checks]


def test_parse_query_rejects_unknown_selector() -> None:
    with pytest.raises(ValueError, match="unknown QQL selector"):
        qql.parse_query("missing.check")


def test_dry_run_returns_successful_structured_results() -> None:
    results = qql.run_checks(qql.parse_query("quality.diff"), dry_run=True)

    assert results == [
        {
            "key": "quality.diff",
            "description": "Git whitespace/conflict-marker check for current tracked diffs.",
            "command": ["git", "diff", "--check"],
            "cwd": str(qql.ROOT),
            "returncode": 0,
            "status": "dry-run",
            "duration_s": results[0]["duration_s"],
        }
    ]


def test_build_report_includes_repo_and_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qql, "_git_value", lambda args: "main" if args[0] == "branch" else "abc123")
    results = qql.run_checks(qql.parse_query("quality.diff"), dry_run=True)

    report = qql.build_report(query="quality.diff", dry_run=True, results=results)

    assert report["schema"] == "metis.qql.report.v1"
    assert report["query"] == "quality.diff"
    assert report["dry_run"] is True
    assert report["ok"] is True
    assert report["repo"] == {
        "root": str(qql.ROOT),
        "branch": "main",
        "commit": "abc123",
    }
    assert report["results"] == results


def test_write_report_creates_parent_and_json_file(tmp_path) -> None:
    report_path = tmp_path / "nested" / "qql-report.json"

    qql.write_report(report_path, {"schema": "metis.qql.report.v1", "ok": True})

    assert report_path.read_text(encoding="utf-8") == '{\n  "schema": "metis.qql.report.v1",\n  "ok": true\n}\n'


def test_summarize_qql_report_outputs_status_and_checks(tmp_path) -> None:
    report_path = tmp_path / "qql-report.json"
    qql.write_report(
        report_path,
        {
            "schema": "metis.qql.report.v1",
            "ok": True,
            "query": "e2e",
            "repo": {"branch": "main", "commit": "abcdef1234567890"},
            "results": [
                {"key": "quality.diff", "status": "ok", "duration_s": 0.12},
                {"key": "ai.load", "status": "ok", "duration_s": 9.8},
            ],
        },
    )

    summary, ok = qql.summarize_report(report_path)

    assert ok is True
    assert "schema: metis.qql.report.v1" in summary
    assert "query: e2e" in summary
    assert "repo: main @ abcdef123456" in summary
    assert "- ai.load: ok (9.8s)" in summary


def test_summarize_ai_report_outputs_load_details(tmp_path) -> None:
    report_path = tmp_path / "ai-smoke.json"
    qql.write_report(
        report_path,
        {
            "schema": "metis.ai_smoke.report.v1",
            "ok": False,
            "api_base": "http://127.0.0.1:7331",
            "direct_chat_repeats": 3,
            "selected_checks": ["system_health", "direct_chat", "direct_chat_load_3"],
            "environment": {
                "python": "C:/Python/python.exe",
                "token_file_exists": True,
            },
            "duration_s": 4.2,
            "results": [
                {"name": "direct_chat_load_3", "status": "failed", "duration_s": 1.25, "error": "bad token"},
            ],
        },
    )

    summary, ok = qql.summarize_report(report_path)

    assert ok is False
    assert "schema: metis.ai_smoke.report.v1" in summary
    assert "direct_chat_repeats: 3" in summary
    assert "selected_checks: system_health, direct_chat, direct_chat_load_3" in summary
    assert "python: C:/Python/python.exe" in summary
    assert "token_file_exists: True" in summary
    assert "- direct_chat_load_3: failed (1.2s) error=bad token" in summary


def test_latest_report_path_returns_newest_json(tmp_path) -> None:
    older = tmp_path / "older.json"
    newer = tmp_path / "newer.json"
    tmp_file = tmp_path / "newer.json.tmp"
    older.write_text("{}", encoding="utf-8")
    newer.write_text("{}", encoding="utf-8")
    tmp_file.write_text("{}", encoding="utf-8")

    newer.touch()

    assert qql.latest_report_path(tmp_path) == newer


def test_latest_report_path_returns_none_when_empty(tmp_path) -> None:
    assert qql.latest_report_path(tmp_path) is None


def test_latest_cli_summarizes_newest_report(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys: pytest.CaptureFixture[str]) -> None:
    report_path = tmp_path / "latest.json"
    qql.write_report(report_path, {"schema": "metis.qql.report.v1", "ok": True, "query": "quality", "results": []})
    monkeypatch.setattr(qql, "latest_report_path", lambda: report_path)

    rc = qql.main(["--latest"])

    assert rc == 0
    assert "query: quality" in capsys.readouterr().out


def test_latest_cli_returns_two_when_no_reports(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(qql, "latest_report_path", lambda: None)

    rc = qql.main(["--latest"])

    assert rc == 2
    assert "no reports found" in capsys.readouterr().err


def test_report_history_returns_newest_first_and_honors_limit(tmp_path) -> None:
    oldest = tmp_path / "oldest.json"
    middle = tmp_path / "middle.json"
    newest = tmp_path / "newest.json"
    ignored = tmp_path / "newest.json.tmp"
    for path in [oldest, middle, newest, ignored]:
        path.write_text("{}", encoding="utf-8")
    os.utime(oldest, (1, 1))
    os.utime(middle, (2, 2))
    os.utime(newest, (3, 3))

    assert qql.report_history(tmp_path, limit=2) == [newest, middle]


def test_format_history_includes_status_query_and_filename(tmp_path) -> None:
    report = tmp_path / "qql-e2e.json"
    qql.write_report(
        report,
        {
            "schema": "metis.qql.report.v1",
            "ok": True,
            "query": "e2e",
            "results": [],
        },
    )

    output = qql.format_history([report])

    assert "[qql] report history" in output
    assert "- qql-e2e.json: ok e2e" in output


def test_history_cli_returns_two_when_empty(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(qql, "report_history", lambda: [])

    rc = qql.main(["--history"])

    assert rc == 2
    assert "no reports found" in capsys.readouterr().out


def test_build_doctor_report_marks_all_checks_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        qql,
        "doctor_checks",
        lambda: [
            {"key": "python", "ok": True, "detail": "python.exe"},
            {"key": "npm", "ok": True, "detail": "npm.cmd"},
        ],
    )
    monkeypatch.setattr(qql, "_git_value", lambda args: "main" if args[0] == "branch" else "abc123")

    report = qql.build_doctor_report()

    assert report["schema"] == "metis.qql.doctor.v1"
    assert report["ok"] is True
    assert report["repo"] == {"root": str(qql.ROOT), "branch": "main", "commit": "abc123"}
    assert report["checks"] == [
        {"key": "python", "ok": True, "detail": "python.exe"},
        {"key": "npm", "ok": True, "detail": "npm.cmd"},
    ]


def test_format_doctor_report_includes_missing_checks() -> None:
    output = qql.format_doctor_report(
        {
            "ok": False,
            "repo": {"branch": "main", "commit": "abcdef1234567890"},
            "checks": [
                {"key": "python", "ok": True, "detail": "python.exe"},
                {"key": "npm", "ok": False, "detail": "missing"},
            ],
        }
    )

    assert "status: failed" in output
    assert "repo: main @ abcdef123456" in output
    assert "- python: ok (python.exe)" in output
    assert "- npm: missing (missing)" in output


def test_doctor_cli_returns_failure_when_requirement_missing(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        qql,
        "build_doctor_report",
        lambda: {
            "schema": "metis.qql.doctor.v1",
            "ok": False,
            "checks": [{"key": "npm", "ok": False, "detail": "missing"}],
        },
    )

    rc = qql.main(["--doctor"])

    assert rc == 1
    assert "- npm: missing (missing)" in capsys.readouterr().out


def test_tests_backend_includes_user_facing_api_contracts() -> None:
    checks = qql.parse_query("tests.backend")

    assert len(checks) == 1
    assert any("test_setup_code_auth.py" in arg for arg in checks[0].command)
    assert any("test_search_notifications.py" in arg for arg in checks[0].command)
    assert any("test_manager_config_models.py" in arg for arg in checks[0].command)
    assert any("test_memory_loop.py" in arg for arg in checks[0].command)
    assert any("test_mts_format.py" in arg for arg in checks[0].command)


def test_parallel_dry_run_preserves_input_order_and_all_ok() -> None:
    checks = qql.parse_query("quality")

    results = qql.run_checks(checks, dry_run=True, parallel=True)

    assert [r["key"] for r in results] == ["quality.diff", "tests.qql", "tests.backend"]
    assert all(r["status"] == "dry-run" for r in results)
    assert all(r["returncode"] == 0 for r in results)


def test_parallel_and_sequential_dry_run_produce_identical_keys() -> None:
    checks = qql.parse_query("quality")

    seq = qql.run_checks(checks, dry_run=True, parallel=False)
    par = qql.run_checks(checks, dry_run=True, parallel=True)

    assert [r["key"] for r in seq] == [r["key"] for r in par]


def test_build_report_includes_parallel_flag() -> None:
    results = qql.run_checks(qql.parse_query("quality.diff"), dry_run=True, parallel=True)

    report = qql.build_report(query="quality.diff", dry_run=True, parallel=True, results=results)

    assert report["parallel"] is True


def test_resolved_command_uses_path_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qql.shutil, "which", lambda name: f"C:/tools/{name}.cmd")

    assert qql._resolved_command(("npm", "run", "lint")) == ("C:/tools/npm.cmd", "run", "lint")


def test_cli_unknown_selector_returns_two(capsys: pytest.CaptureFixture[str]) -> None:
    rc = qql.main(["missing.check"])

    assert rc == 2
    assert "unknown QQL selector" in capsys.readouterr().err
