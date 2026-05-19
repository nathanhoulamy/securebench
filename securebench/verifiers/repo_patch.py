"""Verifier for image-backed repo-patch benchmark-pack tasks."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Callable

from securebench.errors import ConfigError
from securebench.sandboxes import CommandResult, DockerSandbox, Sandbox
from securebench.tasks import SecureBenchTask, resource_text, resource_value
from securebench.verifiers.base import VerificationResult, Verifier
from securebench.verifiers.code_completion import environment_image_for_task


SandboxFactory = Callable[..., Sandbox]
DEFAULT_CANDIDATE_PATCH = "securebench/candidate.patch"
DEFAULT_TEST_PATCH = "securebench/evaluation_inputs/test.patch"


class RepoPatchVerifier(Verifier):
    """Apply a candidate patch in a benchmark image and run declared checks."""

    def __init__(
        self,
        *,
        sandbox_factory: SandboxFactory | None = None,
        timeout_seconds: float = 300.0,
        candidate_patch_path: str = DEFAULT_CANDIDATE_PATCH,
        test_patch_path: str = DEFAULT_TEST_PATCH,
        workspace_mount_target: str = "/securebench-workspace",
    ) -> None:
        self.sandbox_factory = sandbox_factory
        self.timeout_seconds = timeout_seconds
        self.candidate_patch_path = candidate_patch_path
        self.test_patch_path = test_patch_path
        self.workspace_mount_target = workspace_mount_target

    def verify(self, task: SecureBenchTask, candidate: str, **context: Any) -> VerificationResult:
        if task.task_type != "repo_patch":
            raise TypeError(f"RepoPatchVerifier requires repo_patch task, got {task.task_type!r}")

        tests = command_tests(task)
        image = environment_image_for_task(task)
        workdir = tests.workdir or environment_workdir_for_task(task)
        timeout = float(context.get("timeout_seconds", tests.timeout_seconds or self.timeout_seconds))
        if not candidate.strip():
            return _failed_result(
                task,
                "repo_patch",
                image,
                workdir,
                "candidate_patch",
                CommandResult(("candidate_patch",), 1, "", "empty candidate patch"),
                failure_reason="empty_candidate_patch",
            )
        sandbox = self._sandbox(image)
        close_sandbox = self.sandbox_factory is None

        try:
            base_commit = resource_text(task, "base_commit")
            head = sandbox.run(["git", "rev-parse", "HEAD"], workdir=workdir, timeout=timeout)
            if head.exit_code != 0:
                return _failed_result(task, "repo_patch", image, workdir, "base_commit", head)

            if tests.setup_patch is not None:
                setup_patch_path = str(context.get("setup_patch_path", "securebench/evaluation_inputs/setup.patch"))
                sandbox.write_file(setup_patch_path, tests.setup_patch)
                apply_setup = sandbox.run(
                    ["git", "apply", "--binary", self._workspace_path(setup_patch_path)],
                    workdir=workdir,
                    timeout=timeout,
                )
                if apply_setup.exit_code != 0:
                    return _failed_result(
                        task,
                        "repo_patch",
                        image,
                        workdir,
                        "setup_patch",
                        apply_setup,
                        base_commit=base_commit,
                        image_commit=head.stdout.strip(),
                    )

            candidate_path = str(context.get("candidate_patch_path", self.candidate_patch_path))
            sandbox.write_file(candidate_path, candidate)
            apply_candidate = sandbox.run(
                ["git", "apply", "--binary", self._workspace_path(candidate_path)],
                workdir=workdir,
                timeout=timeout,
            )
            if apply_candidate.exit_code != 0:
                return _failed_result(
                    task,
                    "repo_patch",
                    image,
                    workdir,
                    "candidate_patch",
                    apply_candidate,
                    base_commit=base_commit,
                    image_commit=head.stdout.strip(),
                )

            if tests.test_patch is not None:
                test_patch_path = str(context.get("test_patch_path", self.test_patch_path))
                sandbox.write_file(test_patch_path, tests.test_patch)
                apply_tests = sandbox.run(
                    ["git", "apply", "--binary", self._workspace_path(test_patch_path)],
                    workdir=workdir,
                    timeout=timeout,
                )
                if apply_tests.exit_code != 0:
                    return _failed_result(
                        task,
                        "repo_patch",
                        image,
                        workdir,
                        "test_patch",
                        apply_tests,
                        base_commit=base_commit,
                        image_commit=head.stdout.strip(),
                    )

            result = sandbox.run(tests.command, workdir=workdir, timeout=timeout)
            passed = result.exit_code == 0
            return VerificationResult(
                task_id=task.id,
                status="passed" if passed else "failed",
                passed=passed,
                score=1.0 if passed else 0.0,
                stdout=result.stdout,
                stderr=result.stderr,
                metadata={
                    "verifier": "repo_patch",
                    "image": image,
                    "workdir": workdir,
                    "base_commit": base_commit,
                    "image_commit": head.stdout.strip(),
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "phase": "checks",
                },
            )
        finally:
            if close_sandbox:
                _close_sandbox(sandbox)

    def _sandbox(self, image: str) -> Sandbox:
        if self.sandbox_factory is not None:
            return self.sandbox_factory(image=image)
        return DockerSandbox(
            image=image,
            network="none",
            read_only=False,
            workspace_mount_target=self.workspace_mount_target,
        )

    def _workspace_path(self, path: str) -> str:
        candidate = PurePosixPath(path)
        if candidate.is_absolute():
            return str(candidate)
        return str(PurePosixPath(self.workspace_mount_target) / candidate)


class CommandTests:
    def __init__(
        self,
        *,
        command: str | tuple[str, ...],
        workdir: str | None,
        timeout_seconds: float | None,
        setup_patch: str | None,
        test_patch: str | None,
    ) -> None:
        self.command = command
        self.workdir = workdir
        self.timeout_seconds = timeout_seconds
        self.setup_patch = setup_patch
        self.test_patch = test_patch


def command_tests(task: SecureBenchTask) -> CommandTests:
    """Return structured command tests for a repo-patch task."""
    tests = resource_value(task, "tests")
    if not isinstance(tests, dict):
        raise ConfigError(f"repo_patch task {task.id!r} requires structured command tests")
    if tests.get("source") != "command":
        raise ConfigError(f"repo_patch task {task.id!r} requires tests.source='command'")
    command = _command(tests.get("command"), task.id)
    workdir = _optional_string(tests.get("workdir"), "tests.workdir")
    timeout_seconds = _optional_positive_number(tests.get("timeout_seconds"), "tests.timeout_seconds")
    setup_patch = _test_patch(tests.get("setup_patch"), task.id)
    test_patch = _test_patch(tests.get("test_patch"), task.id)
    return CommandTests(
        command=command,
        workdir=workdir,
        timeout_seconds=timeout_seconds,
        setup_patch=setup_patch,
        test_patch=test_patch,
    )


def environment_workdir_for_task(task: SecureBenchTask) -> str:
    """Return the benchmark environment workdir selected for repo-patch checks."""
    metadata = task.metadata if isinstance(task.metadata, dict) else {}
    environment = metadata.get("environment")
    workdir = environment.get("workdir") if isinstance(environment, dict) else None
    if not isinstance(workdir, str) or not workdir.strip():
        raise ConfigError(
            "repo_patch verification requires benchmark environment.workdir; "
            "set defaults.environment.workdir in the manifest or environment.workdir on the benchmark row"
        )
    return workdir.strip()


def _command(value: object, task_id: str) -> str | tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, list) and value and all(isinstance(item, str) and item.strip() for item in value):
        return tuple(value)
    raise ConfigError(f"repo_patch task {task_id!r} requires tests.command as a non-empty string or string array")


def _test_patch(value: object, task_id: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, dict):
        patch = value.get("patch")
        if value.get("source") == "inline" and isinstance(patch, str) and patch.strip():
            return patch
    raise ConfigError(f"repo_patch task {task_id!r} has invalid tests.test_patch")


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ConfigError(f"{field} must be a non-empty string")


def _optional_positive_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    raise ConfigError(f"{field} must be a positive number")


def _failed_result(
    task: SecureBenchTask,
    verifier: str,
    image: str,
    workdir: str,
    phase: str,
    result: CommandResult,
    **metadata: object,
) -> VerificationResult:
    return VerificationResult(
        task_id=task.id,
        status="failed",
        passed=False,
        score=0.0,
        stdout=result.stdout,
        stderr=result.stderr,
        metadata={
            "verifier": verifier,
            "image": image,
            "workdir": workdir,
            "command": result.command,
            "exit_code": result.exit_code,
            "phase": phase,
            **metadata,
        },
    )


def _close_sandbox(sandbox: Sandbox) -> None:
    close = getattr(sandbox, "close", None)
    if callable(close):
        close()
