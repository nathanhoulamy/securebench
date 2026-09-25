"""Run ``securebench.cli run`` and keep host-side timing and raw agent events.

SecureBench's results.jsonl has no timing or token usage, and its agent trace
drops the ``turn.completed`` usage events. This wrapper runs the CLI in-process
with an observation-only hook on the progress reporter:

* ``<output>/campaign-events.jsonl``: every progress event, host wall-clock
  timestamped (``producer_start``, ``candidate_capture_done``, ...).
* ``<output>/campaign-agent-raw.jsonl``: every raw Codex stdout line.

It does not change execution beyond ``--show-agent-output`` (the switch that
streams Codex output). Token counts parsed from the raw lines are reported by
Codex inside the Agent environment, so they are untrusted observations; they
are used only for cost accounting, never for verdicts.

Usage: python -m tools.native_baseline.sb_run --config C --output-dir O [--env-file .env] [--resume]
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

from securebench import cli, progress

_LOCK = threading.Lock()
_OUT: dict[str, Path] = {}


def _append(name: str, record: dict) -> None:
    path = _OUT.get(name)
    if path is None:
        return
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str) + "\n")


def _install_hook() -> None:
    original_event = progress.StreamProgressReporter.event

    def event(self, name, **fields):
        now = time.time()
        if name == "agent_output":
            _append("raw", {"t": now, "stream": fields.get("stream"), "line": fields.get("line")})
        else:
            _append("events", {"t": now, "event": name,
                               **{k: v for k, v in fields.items() if k in {
                                   "task_id", "status", "passed", "score", "error",
                                   "output_dir", "candidate_type", "exit_code"}}})
        return original_event(self, name, **fields)

    progress.StreamProgressReporter.event = event

    # SecureBench only streams output for commands containing "codex exec",
    # but its Codex command is "codex <config args> exec ...", so
    # --show-agent-output never streams (ISSUES.md I-17). Recognise the real
    # command shape; this only switches on line streaming of the same process.
    import re
    from securebench.sandboxes import docker as docker_sandbox

    pattern = re.compile(r"\bcodex\b.*\bexec\b", re.DOTALL)
    docker_sandbox._is_codex_agent_command = lambda command: bool(pattern.search(" ".join(command)))


def main(argv: list[str]) -> int:
    output_dir = Path(argv[argv.index("--output-dir") + 1])
    output_dir.mkdir(parents=True, exist_ok=True)
    _OUT["events"] = output_dir / "campaign-events.jsonl"
    _OUT["raw"] = output_dir / "campaign-agent-raw.jsonl"
    _install_hook()
    started = time.time()
    _append("events", {"t": started, "event": "campaign_wrapper_start"})
    code = cli.main(["run", *argv, "--show-agent-output"])
    _append("events", {"t": time.time(), "event": "campaign_wrapper_done", "exit_code": code})
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
