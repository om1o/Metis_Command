from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tool_runtime import SessionExecutionLog, ToolRunner


class _FlakyTool:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, x: int) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            err = RuntimeError("transient failure")
            setattr(err, "retryable", True)
            raise err
        return {"ok": True, "x": x}


def main() -> int:
    events: list[dict[str, Any]] = []
    flaky = _FlakyTool()

    reg = {"flaky": flaky}
    log = SessionExecutionLog("selfcheck")
    runner = ToolRunner(reg, on_event=events.append, session_log=log)

    res = runner.run("flaky", {"x": 5}, agent="selfcheck", max_retries=2, timeout_s=2)
    assert res.ok, f"expected ok result, got: {res}"
    assert flaky.calls == 2, f"expected 2 calls due to retry, got {flaky.calls}"
    types = [e.get("type") for e in events]
    assert "tool_start" in types and "tool_end" in types and "error" in types, f"unexpected event types: {types}"
    assert types[-1] == "tool_end", f"expected last event tool_end, got {types[-1]}"

    print("OK: tool_runtime emitted events, retried, and persisted log.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

