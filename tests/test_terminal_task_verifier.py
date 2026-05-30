from pathlib import Path

import pytest

from securebench.benchmark_compiler import compile_benchmark_row
from securebench.benchmark_pack import BenchmarkPackManifest, BenchmarkRow
from securebench.errors import ConfigError
from securebench.sandboxes import CommandResult
from securebench.dangerous_commands import VerificationPolicy
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


def manifest(tmp_path):
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text("id: pack\nversion: 1\n")
    hidden = tmp_path / "hidden"
    hidden.mkdir(exist_ok=True)
    return BenchmarkPackManifest(id="pack", version=1, path=manifest_path)


def write_hidden(tmp_path, path, content="assert True\n"):
    target = tmp_path / "hidden" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def terminal_task(tmp_path):
    write_hidden(tmp_path, "checks/test_outputs.py")
    return compile_benchmark_row(
        BenchmarkRow(
            id="term-1",
            family="terminal_task",
            input={"instructions": "Create output.txt"},
            eval={
                "checker": {
                    "source": "pytest",
                    "path": "checks/test_outputs.py",
                    "timeout_seconds": 12,
                },
                "expected_state": {"file": "output.txt"},
            },
            environment={"image": "python:3.12-slim"},
        ),
        manifest=manifest(tmp_path),
    )


def app_terminal_task(tmp_path):
    write_hidden(tmp_path, "checks/test_outputs.py")
    return compile_benchmark_row(
        BenchmarkRow(
            id="term-app",
            family="terminal_task",
            input={"instructions": "Create output.txt"},
            eval={
                "checker": {
                    "source": "pytest",
                    "path": "checks/test_outputs.py",
                    "timeout_seconds": 12,
                },
            },
            environment={"image": "python:3.12-slim", "workdir": "/app"},
        ),
        manifest=manifest(tmp_path),
    )


def chroot_terminal_task(tmp_path):
    write_hidden(tmp_path, "checks/run-tests.sh", "#!/bin/sh\ntrue\n")
    return compile_benchmark_row(
        BenchmarkRow(
            id="term-chroot",
            family="terminal_task",
            input={"instructions": "Create output.txt"},
            eval={
                "needed_commands": ["chroot"],
                "checker": {
                    "source": "script",
                    "path": "checks/run-tests.sh",
                    "timeout_seconds": 12,
                },
            },
            environment={"image": "python:3.12-slim"},
        ),
        manifest=manifest(tmp_path),
    )


def environment_timeout_terminal_task(tmp_path):
    write_hidden(tmp_path, "checks/test_outputs.py")
    return compile_benchmark_row(
        BenchmarkRow(
            id="term-env-timeout",
            family="terminal_task",
            input={"instructions": "Create output.txt"},
            eval={
                "checker": {
                    "source": "pytest",
                    "path": "checks/test_outputs.py",
                },
            },
            environment={"image": "python:3.12-slim", "timeout_seconds": 77},
        ),
        manifest=manifest(tmp_path),
    )


def test_terminal_task_verifier_runs_checker_against_workspace(tmp_path):
    verifier = TerminalTaskVerifier(sandbox_factory=FakeSandbox)

    result = verifier.verify(terminal_task(tmp_path), str(tmp_path))

    assert result.passed is True
    assert result.score == 1.0
    assert result.stdout == "ok"
    assert result.metadata["verifier"] == "terminal_task"
    assert result.metadata["image"] == "python:3.12-slim"
    assert result.metadata["phase"] == "checker"
    assert (tmp_path / "securebench" / "evaluation_inputs" / "checker.json").exists()
    assert (tmp_path / "securebench" / "evaluator" / "expected_state.json").exists() is False
    sandbox = FakeSandbox.instances[-1]
    command, workdir, timeout = sandbox.commands[0]
    assert command.startswith(
        "SECUREBENCH_WORKSPACE='/workspace' SECUREBENCH_EVALUATOR='/opt/securebench/evaluator' "
        "SECUREBENCH_CHECKER_TARGET='/opt/securebench/evaluator/checks/test_outputs.py' python3 - <<'PY'"
    )
    assert workdir == "/workspace"
    assert timeout == 12.0


def test_terminal_task_verifier_uses_environment_timeout_when_checker_timeout_missing(tmp_path):
    verifier = TerminalTaskVerifier(sandbox_factory=FakeSandbox)

    verifier.verify(environment_timeout_terminal_task(tmp_path), str(tmp_path))

    sandbox = FakeSandbox.instances[-1]
    command, workdir, timeout = sandbox.commands[0]
    assert "SECUREBENCH_CHECKER_TARGET='/opt/securebench/evaluator/checks/test_outputs.py'" in command
    assert workdir == "/workspace"
    assert timeout == 77.0


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

    result = verifier.verify(terminal_task(tmp_path), str(tmp_path))

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

    result = TerminalTaskVerifier().verify(app_terminal_task(tmp_path), str(tmp_path))

    assert result.passed is True
    assert created["workspace_mount_target"] == "/app"
    assert "cap_drop" not in created


def test_terminal_task_verifier_mounts_checker_inputs_read_only(monkeypatch, tmp_path):
    created = {}

    class CapturingSandbox(FakeSandbox):
        def __init__(self, **kwargs):
            created.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr("securebench.verifiers.terminal_task.DockerSandbox", CapturingSandbox)

    TerminalTaskVerifier().verify(terminal_task(tmp_path), str(tmp_path))

    mounts = created["mounts"]
    assert len(mounts) == 2
    assert mounts[0].source == tmp_path / "securebench" / "evaluation_inputs" / "checker.json"
    assert mounts[0].target == "securebench/evaluation_inputs/checker.json"
    assert mounts[0].read_only is True
    assert mounts[1].source == tmp_path / "hidden" / "checks"
    assert mounts[1].target == "/opt/securebench/evaluator/checks"
    assert mounts[1].read_only is True


def test_terminal_task_verifier_denies_dangerous_commands_by_default(monkeypatch, tmp_path):
    created = {}

    class CapturingSandbox(FakeSandbox):
        def __init__(self, **kwargs):
            created.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr("securebench.verifiers.terminal_task.DockerSandbox", CapturingSandbox)

    result = TerminalTaskVerifier().verify(chroot_terminal_task(tmp_path), str(tmp_path))

    assert result.status == "failed"
    assert result.passed is False
    assert result.metadata["failure_reason"] == "verifier_dangerous_command_denied"
    assert result.metadata["denied_command"] == "chroot"
    assert result.metadata["needed_commands"] == ("chroot",)
    assert result.metadata["tester_disallow_dangerous_commands"] is True
    assert "dangerous verifier command" in result.stderr
    assert created == {}


def test_terminal_task_verifier_allows_declared_chroot_when_tester_opts_in(monkeypatch, tmp_path):
    created = {}

    class CapturingSandbox(FakeSandbox):
        def __init__(self, **kwargs):
            created.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr("securebench.verifiers.terminal_task.DockerSandbox", CapturingSandbox)

    result = TerminalTaskVerifier().verify(
        chroot_terminal_task(tmp_path),
        str(tmp_path),
        verification_policy=VerificationPolicy(disallow_dangerous_commands=False),
    )

    assert result.passed is True
    assert created["cap_add"] == ("SYS_CHROOT",)


def test_terminal_task_verifier_tester_deny_overrides_dangerous_command_opt_in(monkeypatch, tmp_path):
    created = {}

    class CapturingSandbox(FakeSandbox):
        def __init__(self, **kwargs):
            created.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr("securebench.verifiers.terminal_task.DockerSandbox", CapturingSandbox)

    result = TerminalTaskVerifier().verify(
        chroot_terminal_task(tmp_path),
        str(tmp_path),
        verification_policy=VerificationPolicy(
            disallow_dangerous_commands=False,
            deny_commands=("chroot",),
        ),
    )

    assert result.status == "failed"
    assert result.metadata["failure_reason"] == "verifier_dangerous_command_denied"
    assert result.metadata["tester_disallow_dangerous_commands"] is False
    assert result.metadata["tester_denied_commands"] == ("chroot",)
    assert created == {}


def test_terminal_task_verifier_does_not_pass_cap_add_without_needed_commands(monkeypatch, tmp_path):
    created = {}

    class CapturingSandbox(FakeSandbox):
        def __init__(self, **kwargs):
            created.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr("securebench.verifiers.terminal_task.DockerSandbox", CapturingSandbox)

    result = TerminalTaskVerifier().verify(
        terminal_task(tmp_path),
        str(tmp_path),
        verification_policy=VerificationPolicy(disallow_dangerous_commands=False),
    )

    assert result.passed is True
    assert "cap_add" not in created


def test_terminal_task_verifier_requires_workspace(tmp_path):
    verifier = TerminalTaskVerifier(sandbox_factory=FakeSandbox)

    with pytest.raises(ConfigError, match="workspace directory"):
        verifier.verify(terminal_task(tmp_path), str(tmp_path / "missing"))
