"""Lightweight progress reporting for interactive benchmark runs."""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import IO, Iterator


_CURRENT_REPORTER: ContextVar["ProgressReporter | None"] = ContextVar(
    "securebench_progress_reporter",
    default=None,
)


class ProgressReporter:
    """Interface for receiving benchmark progress events."""

    def event(self, name: str, **fields: object) -> None:
        """Handle one progress event."""


class NullProgressReporter(ProgressReporter):
    """Progress reporter that intentionally emits nothing."""

    def event(self, name: str, **fields: object) -> None:
        return None


class StreamProgressReporter(ProgressReporter):
    """Human-readable progress reporter for CLI runs."""

    def __init__(
        self,
        *,
        stream: IO[str] = sys.stderr,
        show_command_output: bool = False,
        show_agent_output: bool = False,
        color: bool | None = None,
    ) -> None:
        self.stream = stream
        self.show_command_output = show_command_output
        self.show_agent_output = show_agent_output
        self.color = stream.isatty() if color is None else color
        self._current_task_id: str | None = None
        self._agent_trace_path: Path | None = None

    def event(self, name: str, **fields: object) -> None:
        self._record_state(name, fields)
        if name == "agent_output":
            self._write_agent_trace(fields)
        line = _format_event(
            name,
            fields,
            show_command_output=self.show_command_output,
            show_agent_output=self.show_agent_output,
            color=self.color,
        )
        if line is None:
            return
        print(line, file=self.stream, flush=True)

    def _record_state(self, name: str, fields: dict[str, object]) -> None:
        if name == "run_start" and self.show_agent_output:
            output_dir = fields.get("output_dir")
            if output_dir is not None:
                self._agent_trace_path = Path(output_dir) / "agent-trace.log"
                self._agent_trace_path.parent.mkdir(parents=True, exist_ok=True)
                self._agent_trace_path.write_text("")
        if name == "task_start":
            task_id = fields.get("task_id")
            self._current_task_id = str(task_id) if task_id is not None else None

    def _write_agent_trace(self, fields: dict[str, object]) -> None:
        if self._agent_trace_path is None:
            return
        line = _agent_output(fields, color=False, include_agent_done=True)
        if line is None:
            return
        task_id = self._current_task_id or "unknown-task"
        with self._agent_trace_path.open("a") as trace:
            trace.write(f"{task_id} | {line}\n")


@contextmanager
def progress_context(reporter: ProgressReporter | None) -> Iterator[None]:
    """Install a progress reporter for nested harness/verifier/sandbox calls."""
    token = _CURRENT_REPORTER.set(reporter)
    try:
        yield
    finally:
        _CURRENT_REPORTER.reset(token)


def emit_progress(name: str, **fields: object) -> None:
    """Emit a progress event if the current run has a reporter."""
    reporter = _CURRENT_REPORTER.get()
    if reporter is None:
        return
    reporter.event(name, **fields)


def wants_agent_output() -> bool:
    """Return whether the active reporter wants live agent output events."""
    reporter = _CURRENT_REPORTER.get()
    return bool(getattr(reporter, "show_agent_output", False))


def _format_event(
    name: str,
    fields: dict[str, object],
    *,
    show_command_output: bool,
    show_agent_output: bool,
    color: bool,
) -> str | None:
    if name == "task_start":
        return (
            f"{_dim('securebench:', color)} "
            f"[{fields.get('index')}/{fields.get('total')}] "
            f"{fields.get('task_id')}"
        )
    if name == "resume":
        return (
            f"{_dim('securebench:', color)} "
            f"resume completed={fields.get('completed')} remaining={fields.get('remaining')}"
        )
    if name == "task_done":
        passed = fields.get("passed")
        status = fields.get("status")
        label = _status_label(status, passed, color)
        return (
            f"{_dim('securebench:', color)} "
            f"{label} {fields.get('task_id')} "
            f"score={fields.get('score')}"
        )
    if name == "image_prune_done":
        return (
            f"{_dim('securebench:', color)} "
            f"removed {fields.get('removed')} benchmark image(s)"
        )
    if name == "image_prune_failed":
        images = fields.get("images")
        count = len(images) if isinstance(images, (list, tuple)) else "unknown"
        return (
            f"{_dim('securebench:', color)} "
            f"image cleanup failed for {count} image(s) "
            f"exit={fields.get('exit_code')}"
        )
    if show_command_output and name == "sandbox_result":
        return _sandbox_output(fields, color=color)
    if show_agent_output and name == "agent_output":
        return _agent_output(fields, color=color, include_agent_done=False)
    return None


def _status_label(status: object, passed: object, color: bool) -> str:
    if passed is True:
        return _green("PASS", color)
    if passed is False:
        return _red("FAIL", color)
    if status == "pending":
        return _yellow("PENDING", color)
    return _yellow(str(status).upper(), color)


def _sandbox_output(fields: dict[str, object], *, color: bool) -> str | None:
    stdout = _clip(fields.get("stdout"), 1000)
    stderr = _clip(fields.get("stderr"), 1000)
    if not stdout and not stderr:
        return None
    lines: list[str] = []
    if stdout:
        lines.append(f"{_dim('stdout:', color)} {stdout}")
    if stderr:
        lines.append(f"{_dim('stderr:', color)} {stderr}")
    return "\n".join(lines)


def _agent_output(
    fields: dict[str, object],
    *,
    color: bool,
    include_agent_done: bool,
) -> str | None:
    line = str(fields.get("line") or "").strip()
    if not line:
        return None
    stream = fields.get("stream")
    if stream == "stderr":
        return f"{_dim('codex stderr:', color)} {_clip(line, 1000)}"
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return f"{_dim('codex:', color)} {_clip(line, 1000)}"
    if not isinstance(event, dict):
        return None
    event_type = event.get("type")
    if event_type == "agent_message":
        text = event.get("text")
        if isinstance(text, str) and text.strip():
            return f"{_dim('codex:', color)} {_clip(text, 1000)}"
    if event_type == "item.started":
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "command_execution":
            return f"{_dim('codex run:', color)} {_clip(item.get('command'), 300)}"
    if event_type == "item.completed":
        if not include_agent_done:
            return None
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "command_execution":
            return (
                f"{_dim('codex done:', color)} "
                f"exit={item.get('exit_code')} {_clip(item.get('command'), 220)}"
            )
    if event_type == "turn.completed":
        return f"{_dim('codex:', color)} turn complete"
    return None


def _green(value: str, color: bool) -> str:
    return _ansi(value, "32", color)


def _red(value: str, color: bool) -> str:
    return _ansi(value, "31", color)


def _yellow(value: str, color: bool) -> str:
    return _ansi(value, "33", color)


def _dim(value: str, color: bool) -> str:
    return _ansi(value, "2", color)


def _ansi(value: str, code: str, color: bool) -> str:
    if not color:
        return value
    return f"\033[{code}m{value}\033[0m"


def _clip(value: object, limit: int) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
