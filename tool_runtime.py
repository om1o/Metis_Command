"""
Tool runtime — reliability-first execution layer for Metis atomic tools.

This module is intentionally UI-agnostic. It emits structured dict events that
match the shapes `dynamic_ui.py` already renders (tool_start/tool_end/error).
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ValidationError, create_model

from artifacts import Artifact, save_artifact
from safety import ConfirmRequired


ToolEventType = Literal["tool_start", "tool_end", "error"]


class CancelledError(RuntimeError):
    pass


class ToolTimeoutError(TimeoutError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str = ""
    input_model: type[BaseModel] | None = None
    allow_when: set[str] = field(default_factory=set)
    retryable: bool = False


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    retryable: bool = False
    duration_ms: int = 0
    attempts: int = 1
    confirm_required: bool = False
    confirm_token: str = ""


@dataclass(frozen=True)
class ToolEvent:
    type: ToolEventType
    agent: str
    tool: str
    ts_ms: int
    duration_ms: int | None = None
    args_summary: dict[str, Any] | None = None
    result_summary: str | None = None
    message: str | None = None
    attempt: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": self.type,
            "agent": self.agent,
            "tool": self.tool,
        }
        if self.duration_ms is not None:
            payload["duration_ms"] = self.duration_ms
        if self.args_summary is not None:
            payload["args"] = self.args_summary
        if self.result_summary is not None:
            payload["result"] = self.result_summary
        if self.message is not None:
            payload["message"] = self.message
        if self.attempt is not None:
            payload["attempt"] = self.attempt
        return payload


def _now_ms() -> int:
    return int(time.time() * 1000)


def _is_cancelled(cancel_token: Any | None) -> bool:
    return bool(cancel_token is not None and getattr(cancel_token, "cancelled", False))


def _summarize_args(args: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if k in ("content", "code", "text") and isinstance(v, str) and len(v) > 240:
            out[k] = v[:240] + "…"
        elif isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)[:240]
    return out


def _summarize_result(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, (str, int, float, bool)):
        s = str(result)
        return s if len(s) <= 800 else s[:800] + "…"
    try:
        s = json.dumps(result, ensure_ascii=False)
        return s if len(s) <= 800 else s[:800] + "…"
    except Exception:
        return str(result)[:800]


def _stable_artifact_id_for_session(session_id: str) -> str:
    h = hashlib.sha1(session_id.encode("utf-8")).hexdigest()[:12]
    return f"toolruns_{h}"


class SessionExecutionLog:
    def __init__(self, session_id: str, *, keep_last: int = 200) -> None:
        self.session_id = session_id
        self.keep_last = keep_last
        self._runs: list[dict[str, Any]] = []

        base = Path("artifacts") / "tool_runs"
        base.mkdir(parents=True, exist_ok=True)
        self.path = base / f"{session_id}.json"

        self._artifact_id = _stable_artifact_id_for_session(session_id)
        self._artifact = Artifact(
            id=self._artifact_id,
            type="doc",
            title=f"tool_runs/{session_id}.json",
            language="json",
            path=str(self.path),
            metadata={"kind": "tool_runs", "session_id": session_id},
        )
        save_artifact(self._artifact)

        self._load_existing()

    def _load_existing(self) -> None:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("runs"), list):
                    self._runs = list(data["runs"])[-self.keep_last :]
        except Exception:
            self._runs = []

    def append_run(self, run: dict[str, Any]) -> None:
        self._runs.append(run)
        if len(self._runs) > self.keep_last:
            self._runs = self._runs[-self.keep_last :]
        self.flush()

    def flush(self) -> None:
        payload = {
            "session_id": self.session_id,
            "updated_at_ms": _now_ms(),
            "runs": self._runs,
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        save_artifact(self._artifact)


def build_pydantic_model_from_callable(fn: Callable[..., Any], name: str) -> type[BaseModel]:
    sig = inspect.signature(fn)
    fields: dict[str, tuple[Any, Any]] = {}
    for p in sig.parameters.values():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.name in ("confirm_token",):
            continue
        ann = p.annotation if p.annotation is not inspect._empty else Any
        default = p.default if p.default is not inspect._empty else ...
        fields[p.name] = (ann, default)
    return create_model(f"{name}Input", **fields)  # type: ignore[arg-type]


class ToolRunner:
    def __init__(
        self,
        registry: dict[str, Callable[..., Any]],
        *,
        specs: dict[str, ToolSpec] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        session_log: SessionExecutionLog | None = None,
    ) -> None:
        self.registry = registry
        self.specs = specs or {}
        self.on_event = on_event
        self.session_log = session_log

    def _emit(self, ev: ToolEvent) -> None:
        if not self.on_event:
            return
        try:
            self.on_event(ev.to_dict())
        except Exception:
            pass

    def run(
        self,
        tool_name: str,
        payload: dict[str, Any],
        *,
        agent: str = "manager",
        cancel_token: Any | None = None,
        timeout_s: float | None = None,
        max_retries: int = 1,
        backoff_base_s: float = 0.6,
        backoff_max_s: float = 8.0,
    ) -> ToolResult:
        if tool_name not in self.registry:
            return ToolResult(ok=False, error=f"unknown tool: {tool_name}", retryable=False, duration_ms=0)

        if _is_cancelled(cancel_token):
            return ToolResult(ok=False, error="cancelled before tool started", retryable=False, duration_ms=0)

        timeout_s = float(timeout_s if timeout_s is not None else os.getenv("METIS_TOOL_TIMEOUT_S", "120"))

        fn = self.registry[tool_name]
        spec = self.specs.get(tool_name)
        input_model: type[BaseModel] | None = spec.input_model if spec else None
        if input_model is None:
            try:
                input_model = build_pydantic_model_from_callable(fn, tool_name)
            except Exception:
                input_model = None

        validated_args = payload
        if input_model is not None:
            try:
                validated_args = input_model.model_validate(payload).model_dump()
            except ValidationError as ve:
                msg = ve.errors(include_url=False)
                return ToolResult(ok=False, error=f"validation_error: {msg}", retryable=False, duration_ms=0)

        attempts = 0
        last_err: str | None = None
        started_overall = time.time()

        while attempts < max(1, max_retries + 1):
            attempts += 1
            if _is_cancelled(cancel_token):
                elapsed = int((time.time() - started_overall) * 1000)
                return ToolResult(ok=False, error="cancelled by user", retryable=False, duration_ms=elapsed, attempts=attempts)

            self._emit(
                ToolEvent(
                    type="tool_start",
                    agent=agent,
                    tool=tool_name,
                    ts_ms=_now_ms(),
                    args_summary=_summarize_args(validated_args),
                    attempt=attempts,
                )
            )

            result_box: dict[str, Any] = {}
            started_attempt = time.time()

            def _call() -> None:
                try:
                    result_box["value"] = fn(**validated_args)
                except ConfirmRequired as cr:
                    result_box["confirm_required"] = str(cr)
                except Exception as e:  # noqa: BLE001
                    result_box["error"] = e

            t = threading.Thread(target=_call, daemon=True, name=f"tool:{tool_name}")
            t.start()

            # Cooperative cancel/timeout.
            while t.is_alive():
                t.join(0.2)
                if _is_cancelled(cancel_token):
                    elapsed = int((time.time() - started_attempt) * 1000)
                    msg = "cancelled by user"
                    self._emit(
                        ToolEvent(
                            type="error",
                            agent=agent,
                            tool=tool_name,
                            ts_ms=_now_ms(),
                            duration_ms=elapsed,
                            message=msg,
                            attempt=attempts,
                        )
                    )
                    return ToolResult(ok=False, error=msg, retryable=False, duration_ms=elapsed, attempts=attempts)
                if time.time() - started_attempt > timeout_s:
                    elapsed = int((time.time() - started_attempt) * 1000)
                    msg = f"tool {tool_name} timed out after {timeout_s:.0f}s"
                    self._emit(
                        ToolEvent(
                            type="error",
                            agent=agent,
                            tool=tool_name,
                            ts_ms=_now_ms(),
                            duration_ms=elapsed,
                            message=msg,
                            attempt=attempts,
                        )
                    )
                    last_err = msg
                    # timeout is usually retryable for transient hangs, but we keep it conservative.
                    break

            elapsed = int((time.time() - started_attempt) * 1000)

            if "confirm_required" in result_box:
                tok = str(result_box.get("confirm_required") or "")
                msg = "confirm_required"
                self._emit(
                    ToolEvent(
                        type="error",
                        agent=agent,
                        tool=tool_name,
                        ts_ms=_now_ms(),
                        duration_ms=elapsed,
                        message=msg,
                        attempt=attempts,
                    )
                )
                res = ToolResult(
                    ok=False,
                    error=msg,
                    retryable=False,
                    duration_ms=elapsed,
                    attempts=attempts,
                    confirm_required=True,
                    confirm_token=tok,
                )
                self._persist_run(tool_name, validated_args, res, agent=agent)
                return res

            if "value" in result_box:
                value = result_box["value"]
                self._emit(
                    ToolEvent(
                        type="tool_end",
                        agent=agent,
                        tool=tool_name,
                        ts_ms=_now_ms(),
                        duration_ms=elapsed,
                        result_summary=_summarize_result(value),
                        attempt=attempts,
                    )
                )
                res = ToolResult(ok=True, data=value, duration_ms=elapsed, attempts=attempts)
                self._persist_run(tool_name, validated_args, res, agent=agent)
                return res

            if isinstance(result_box.get("error"), BaseException):
                e: BaseException = result_box["error"]
                err = f"{type(e).__name__}: {e}"
                last_err = err
                retryable = bool(getattr(e, "retryable", False) or (spec.retryable if spec else False))
                self._emit(
                    ToolEvent(
                        type="error",
                        agent=agent,
                        tool=tool_name,
                        ts_ms=_now_ms(),
                        duration_ms=elapsed,
                        message=err,
                        attempt=attempts,
                    )
                )
                if retryable and attempts <= max_retries:
                    sleep_s = min(backoff_max_s, backoff_base_s * (2 ** (attempts - 1)))
                    sleep_s = sleep_s * (0.8 + random.random() * 0.4)
                    time.sleep(sleep_s)
                    continue
                res = ToolResult(
                    ok=False,
                    error=err,
                    retryable=retryable,
                    duration_ms=elapsed,
                    attempts=attempts,
                )
                self._persist_run(tool_name, validated_args, res, agent=agent)
                return res

            # timeout path
            retryable = True
            if retryable and attempts <= max_retries:
                sleep_s = min(backoff_max_s, backoff_base_s * (2 ** (attempts - 1)))
                sleep_s = sleep_s * (0.8 + random.random() * 0.4)
                time.sleep(sleep_s)
                continue
            res = ToolResult(ok=False, error=last_err or "tool failed", retryable=retryable, duration_ms=elapsed, attempts=attempts)
            self._persist_run(tool_name, validated_args, res, agent=agent)
            return res

        elapsed = int((time.time() - started_overall) * 1000)
        res = ToolResult(ok=False, error=last_err or "tool failed", retryable=False, duration_ms=elapsed, attempts=attempts)
        self._persist_run(tool_name, validated_args, res, agent=agent)
        return res

    def _persist_run(self, tool: str, args: dict[str, Any], res: ToolResult, *, agent: str) -> None:
        if not self.session_log:
            return
        try:
            self.session_log.append_run(
                {
                    "ts_ms": _now_ms(),
                    "agent": agent,
                    "tool": tool,
                    "ok": res.ok,
                    "duration_ms": res.duration_ms,
                    "attempts": res.attempts,
                    "retryable": res.retryable,
                    "error": res.error,
                    "args": _summarize_args(args),
                }
            )
        except Exception:
            pass

