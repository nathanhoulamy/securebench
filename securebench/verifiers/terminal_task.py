"""Verifier for terminal benchmark-pack tasks."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from securebench.errors import ConfigError
from securebench.sandboxes import CommandResult, DockerSandbox, HostSandbox, Sandbox
from securebench.tasks import SecureBenchTask, resource_value
from securebench.verifiers.base import VerificationResult, Verifier, timeout_metadata
from securebench.verifiers.code_completion import environment_image_for_task
from securebench.harnesses.shared import task_timeout_seconds, workspace_mount_target_for_task
from securebench.workspaces.materialization import VisibilityAwareMaterializer, docker_read_only_mounts


SandboxFactory = Callable[..., Sandbox]
DEFAULT_TIMEOUT_SECONDS = 300.0


class TerminalTaskVerifier(Verifier):
    """Run a trusted checker against the final workspace state."""

    def __init__(
        self,
        *,
        sandbox_factory: SandboxFactory | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.sandbox_factory = sandbox_factory
        self.timeout_seconds = timeout_seconds
        self.materializer = VisibilityAwareMaterializer()

    def verify(self, task: SecureBenchTask, candidate: str, **context: Any) -> VerificationResult:
        if task.task_type != "terminal_task":
            raise TypeError(f"TerminalTaskVerifier requires terminal_task task, got {task.task_type!r}")

        workspace_root = Path(candidate).resolve() if candidate else None
        if workspace_root is None or not workspace_root.exists() or not workspace_root.is_dir():
            raise ConfigError(f"terminal_task task {task.id!r} requires a produced workspace directory")

        checker = checker_for_task(task)
        image = environment_image_for_task(task)
        timeout = float(
            context.get(
                "timeout_seconds",
                checker.timeout_seconds or task_timeout_seconds(task) or self.timeout_seconds,
            )
        )

        staging = HostSandbox(root=workspace_root)
        plan = self.materializer.materialize(task, staging, "test_sandbox")
        sandbox = self._sandbox(task, image, workspace_root, plan)
        close_sandbox = self.sandbox_factory is None
        try:
            result = sandbox.run(checker.command, workdir=checker.workdir, timeout=timeout)
            passed = result.exit_code == 0
            return VerificationResult(
                task_id=task.id,
                status="passed" if passed else "failed",
                passed=passed,
                score=1.0 if passed else 0.0,
                stdout=result.stdout,
                stderr=result.stderr,
                metadata={
                    "verifier": "terminal_task",
                    "image": image,
                    "workspace_root": str(workspace_root),
                    "workdir": checker.workdir,
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "phase": "checker",
                    **timeout_metadata(result),
                },
            )
        finally:
            if close_sandbox:
                _close_sandbox(sandbox)

    def _sandbox(self, task: SecureBenchTask, image: str, workspace_root: Path, plan: Any) -> Sandbox:
        if self.sandbox_factory is not None:
            return self.sandbox_factory(image=image, root=workspace_root)
        return DockerSandbox(
            image=image,
            root=workspace_root,
            network="none",
            cap_drop=(),
            read_only=False,
            mounts=docker_read_only_mounts(plan, workspace_root),
            workspace_mount_target=workspace_mount_target_for_task(task),
        )


class TerminalChecker:
    def __init__(
        self,
        *,
        command: str | tuple[str, ...],
        workdir: str | None,
        timeout_seconds: float | None,
    ) -> None:
        self.command = command
        self.workdir = workdir
        self.timeout_seconds = timeout_seconds


def checker_for_task(task: SecureBenchTask) -> TerminalChecker:
    checker = resource_value(task, "checker")
    if not isinstance(checker, dict):
        raise ConfigError(f"terminal_task task {task.id!r} requires structured checker")
    return TerminalChecker(
        command=_command(checker.get("command"), task.id),
        workdir=_optional_string(checker.get("workdir"), "checker.workdir"),
        timeout_seconds=_optional_positive_number(checker.get("timeout_seconds"), "checker.timeout_seconds"),
    )


def _command(value: object, task_id: str) -> str | tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, list) and value and all(isinstance(item, str) and item.strip() for item in value):
        return tuple(value)
    raise ConfigError(f"terminal_task task {task_id!r} requires checker.command as a non-empty string or string array")


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


def _close_sandbox(sandbox: Sandbox) -> None:
    close = getattr(sandbox, "close", None)
    if callable(close):
        close()

