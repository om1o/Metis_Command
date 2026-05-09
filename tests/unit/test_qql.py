from __future__ import annotations

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


def test_resolved_command_uses_path_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qql.shutil, "which", lambda name: f"C:/tools/{name}.cmd")

    assert qql._resolved_command(("npm", "run", "lint")) == ("C:/tools/npm.cmd", "run", "lint")


def test_cli_unknown_selector_returns_two(capsys: pytest.CaptureFixture[str]) -> None:
    rc = qql.main(["missing.check"])

    assert rc == 2
    assert "unknown QQL selector" in capsys.readouterr().err
