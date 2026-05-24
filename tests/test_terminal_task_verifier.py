from pathlib import Path

import pytest

from securebench.benchmark_compiler import compile_benchmark_row
from securebench.benchmark_pack import BenchmarkPackManifest, BenchmarkRow
from securebench.errors import ConfigError
from securebench.sandboxes import CommandResult
from securebench.verifiers.terminal_task import TerminalTaskVerifier


class FakeSandbox:
    instances = []

    def __init__(self, *, image, root=None, **kwargs):
        self.image = image
        self.root = Path(root)
        self.kwargs = kwargs
        self.commands = []
        FakeSandbox.instances.append(self)

    def run(self, command, *, workdir=None, timeout=None):
        self.commands.append((command, workdir, timeout))
        return CommandResult(tuple(command) if not isinstance(command, str) else ("sh", "-lc", command), 0, "ok", "")

    def write_file(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    def read_file(self, path):
        return (self.root / path).read_text()

    def extract_file(self, path):
        return (self.root / path).read_bytes()


def terminal_task():
    return compile_benchmark_row(
        BenchmarkRow(
            id="term-1",
            family="terminal_task",
            input={"instructions": "Create output.txt"},
            eval={
                "checker": {
                    "command": ["python", "securebench/evaluation_inputs/checker.json"],
                    "workdir": "/workspace",
                    "timeout_seconds": 12,
                },
                "expected_state": {"file": "output.txt"},
            },
            environment={"image": "python:3.12-slim"},
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )


def app_terminal_task():
    return compile_benchmark_row(
        BenchmarkRow(
            id="term-app",
            family="terminal_task",
            input={"instructions": "Create output.txt"},
            eval={
                "checker": {
                    "command": "test -f output.txt",
                    "workdir": "/app",
                    "timeout_seconds": 12,
                },
            },
            environment={"image": "python:3.12-slim", "workdir": "/app"},
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )


def environment_timeout_terminal_task():
    return compile_benchmark_row(
        BenchmarkRow(
            id="term-env-timeout",
            family="terminal_task",
            input={"instructions": "Create output.txt"},
            eval={
                "checker": {
                    "command": "test -f output.txt",
                    "workdir": "/workspace",
                },
            },
            environment={"image": "python:3.12-slim", "timeout_seconds": 77},
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1),
    )


def test_terminal_task_verifier_runs_checker_against_workspace(tmp_path):
    verifier = TerminalTaskVerifier(sandbox_factory=FakeSandbox)

    result = verifier.verify(terminal_task(), str(tmp_path))

    assert result.passed is True
    assert result.score == 1.0
    assert result.stdout == "ok"
    assert result.metadata["verifier"] == "terminal_task"
    assert result.metadata["image"] == "python:3.12-slim"
    assert result.metadata["phase"] == "checker"
    assert (tmp_path / "securebench" / "evaluation_inputs" / "checker.json").exists()
    assert (tmp_path / "securebench" / "evaluator" / "expected_state.json").exists() is False
    sandbox = FakeSandbox.instances[-1]
    assert sandbox.commands == [(("python", "securebench/evaluation_inputs/checker.json"), "/workspace", 12.0)]


def test_terminal_task_verifier_uses_environment_timeout_when_checker_timeout_missing(tmp_path):
    verifier = TerminalTaskVerifier(sandbox_factory=FakeSandbox)

    verifier.verify(environment_timeout_terminal_task(), str(tmp_path))

    sandbox = FakeSandbox.instances[-1]
    assert sandbox.commands == [("test -f output.txt", "/workspace", 77.0)]


def test_terminal_task_verifier_reports_checker_timeout(tmp_path):
    class TimeoutSandbox(FakeSandbox):
        def run(self, command, *, workdir=None, timeout=None):
            self.commands.append((command, workdir, timeout))
            return CommandResult(
                ("sh", "-lc", command) if isinstance(command, str) else tuple(command),
                124,
                "partial out",
                "partial err",
                timed_out=True,
                timeout_seconds=timeout,
            )

    verifier = TerminalTaskVerifier(sandbox_factory=TimeoutSandbox)

    result = verifier.verify(terminal_task(), str(tmp_path))

    assert result.status == "failed"
    assert result.passed is False
    assert result.score == 0.0
    assert result.metadata["failure_reason"] == "verifier_timeout"
    assert result.metadata["timed_out"] is True
    assert result.metadata["timeout_seconds"] == 12.0


def test_terminal_task_verifier_mounts_app_workspace(monkeypatch, tmp_path):
    created = {}

    class CapturingSandbox(FakeSandbox):
        def __init__(self, **kwargs):
            created.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr("securebench.verifiers.terminal_task.DockerSandbox", CapturingSandbox)

    result = TerminalTaskVerifier().verify(app_terminal_task(), str(tmp_path))

    assert result.passed is True
    assert created["workspace_mount_target"] == "/app"
    assert created["cap_drop"] == ()


def test_terminal_task_verifier_requires_workspace(tmp_path):
    verifier = TerminalTaskVerifier(sandbox_factory=FakeSandbox)

    with pytest.raises(ConfigError, match="workspace directory"):
        verifier.verify(terminal_task(), str(tmp_path / "missing"))
