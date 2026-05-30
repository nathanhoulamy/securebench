"""Verifier for terminal benchmark-pack tasks."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Callable

from securebench.errors import ConfigError
from securebench.dangerous_commands import (
    VerificationPolicy,
    dangerous_command_list,
    parse_verification_policy,
    resolve_dangerous_commands,
)
from securebench.progress import emit_progress
from securebench.sandboxes import CommandResult, DockerBindMount, DockerSandbox, HostSandbox, Sandbox
from securebench.tasks import SecureBenchTask, resource_value
from securebench.verifiers.base import VerificationResult, Verifier, timeout_metadata
from securebench.verifiers.code_completion import environment_image_for_task
from securebench.harnesses.shared import task_timeout_seconds, workspace_mount_target_for_task
from securebench.workspaces.materialization import VisibilityAwareMaterializer, docker_read_only_mounts


SandboxFactory = Callable[..., Sandbox]
DEFAULT_TIMEOUT_SECONDS = 300.0
EVALUATOR_ROOT = PurePosixPath("/opt/securebench/evaluator")


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
        verification_policy = verification_policy_from_context(context)
        dangerous_command_decision = resolve_dangerous_commands(
            needed_commands_for_task(task),
            verification_policy,
        )
        if not dangerous_command_decision.allowed:
            return dangerous_command_denial_result(
                task,
                checker,
                image,
                dangerous_command_decision,
                verification_policy,
            )
        timeout = float(
            context.get(
                "timeout_seconds",
                checker.timeout_seconds or task_timeout_seconds(task) or self.timeout_seconds,
            )
        )

        staging = HostSandbox(root=workspace_root)
        plan = self.materializer.materialize(task, staging, "test_sandbox")
        sandbox = self._sandbox(
            task,
            checker,
            image,
            workspace_root,
            plan,
            cap_add=dangerous_command_decision.cap_add,
        )
        close_sandbox = self.sandbox_factory is None
        try:
            result = sandbox.run(
                checker_command(task, checker),
                workdir=workspace_mount_target_for_task(task),
                timeout=timeout,
            )
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
                    "workdir": workspace_mount_target_for_task(task),
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "phase": "checker",
                    "checker_source": checker.source,
                    "checker_path": checker.path,
                    **timeout_metadata(result),
                },
            )
        finally:
            if close_sandbox:
                _close_sandbox(sandbox)

    def _sandbox(
        self,
        task: SecureBenchTask,
        checker: "TerminalChecker",
        image: str,
        workspace_root: Path,
        plan: Any,
        *,
        cap_add: tuple[str, ...] = (),
    ) -> Sandbox:
        if self.sandbox_factory is not None:
            kwargs: dict[str, Any] = {"image": image, "root": workspace_root}
            if cap_add:
                kwargs["cap_add"] = cap_add
            return self.sandbox_factory(**kwargs)
        docker_kwargs: dict[str, Any] = {}
        if cap_add:
            docker_kwargs["cap_add"] = cap_add
        return DockerSandbox(
            image=image,
            root=workspace_root,
            network="none",
            read_only=False,
            mounts=(
                *docker_read_only_mounts(plan, workspace_root),
                trusted_checker_mount(task, checker),
            ),
            workspace_mount_target=workspace_mount_target_for_task(task),
            **docker_kwargs,
        )


class TerminalChecker:
    def __init__(
        self,
        *,
        source: str,
        path: str,
        timeout_seconds: float | None,
    ) -> None:
        self.source = source
        self.path = path
        self.timeout_seconds = timeout_seconds


def checker_for_task(task: SecureBenchTask) -> TerminalChecker:
    checker = resource_value(task, "checker")
    if not isinstance(checker, dict):
        raise ConfigError(f"terminal_task task {task.id!r} requires structured checker")
    return TerminalChecker(
        source=_checker_source(checker.get("source"), task.id),
        path=_checker_path(checker.get("path"), task.id),
        timeout_seconds=_optional_positive_number(checker.get("timeout_seconds"), "checker.timeout_seconds"),
    )


def checker_command(task: SecureBenchTask, checker: TerminalChecker) -> str:
    """Return the trusted checker command run from the candidate workspace."""
    workspace = workspace_mount_target_for_task(task)
    evaluator = trusted_checker_target(checker)
    exports = (
        f"SECUREBENCH_WORKSPACE={_shell_quote(workspace)} "
        f"SECUREBENCH_EVALUATOR={_shell_quote(str(EVALUATOR_ROOT))} "
    )
    if checker.source == "pytest":
        return f"{exports}SECUREBENCH_CHECKER_TARGET={_shell_quote(str(evaluator))} python3 - <<'PY'\n{_PYTEST_COMPAT_RUNNER}\nPY"
    if checker.source == "script":
        test_dir = evaluator.parent / "tests"
        return f"{exports}TEST_DIR={_shell_quote(str(test_dir))} bash {_shell_quote(str(evaluator))}"
    raise ConfigError(f"terminal_task checker source is unsupported: {checker.source!r}")


def trusted_checker_mount(task: SecureBenchTask, checker: TerminalChecker) -> DockerBindMount:
    """Return the read-only mount for trusted checker code."""
    source = trusted_checker_source(task, checker)
    target = trusted_checker_target(checker)
    if source.is_file():
        return DockerBindMount(source=source.parent, target=str(target.parent), read_only=True)
    return DockerBindMount(source=source, target=str(target), read_only=True)


def trusted_checker_source(task: SecureBenchTask, checker: TerminalChecker) -> Path:
    """Resolve checker.path under the benchmark eval asset root."""
    manifest_dir = _manifest_dir(task)
    eval_root = _eval_asset_root(task, manifest_dir)
    source = (eval_root / checker.path).resolve()
    if not source.is_relative_to(eval_root):
        raise ConfigError(f"terminal_task checker.path escapes eval asset root: {checker.path}")
    if not source.exists():
        raise ConfigError(f"terminal_task checker.path does not exist: {checker.path}")
    return source


def trusted_checker_target(checker: TerminalChecker) -> PurePosixPath:
    path = PurePosixPath(checker.path)
    if path.is_absolute() or ".." in path.parts or str(path) in ("", "."):
        raise ConfigError(f"terminal_task checker.path must be a safe relative path: {checker.path!r}")
    return EVALUATOR_ROOT / path


def needed_commands_for_task(task: SecureBenchTask) -> tuple[str, ...]:
    return dangerous_command_list(
        resource_value(task, "needed_commands"),
        f"terminal_task task {task.id!r} eval.needed_commands",
    )


def verification_policy_from_context(context: dict[str, Any]) -> VerificationPolicy:
    policy = context.get("verification_policy")
    if isinstance(policy, VerificationPolicy):
        return policy
    return parse_verification_policy(policy)


def dangerous_command_denial_result(
    task: SecureBenchTask,
    checker: TerminalChecker,
    image: str,
    decision: Any,
    policy: VerificationPolicy,
) -> VerificationResult:
    denied_command = decision.denied_commands[0] if decision.denied_commands else ""
    message = (
        "Verifier sandbox denied dangerous command allowance"
        f"{f' {denied_command!r}' if denied_command else ''}: {decision.reason}"
    )
    emit_progress(
        "verifier_policy_denied",
        task_id=task.id,
        denied_command=denied_command,
        reason=decision.reason,
    )
    return VerificationResult(
        task_id=task.id,
        status="failed",
        passed=False,
        score=0.0,
        stderr=message + "\n",
        metadata={
            "verifier": "terminal_task",
            "image": image,
            "workdir": None,
            "command": None,
            "exit_code": None,
            "phase": "checker",
            "checker_source": checker.source,
            "checker_path": checker.path,
            "failure_reason": "verifier_dangerous_command_denied",
            "denied_command": denied_command,
            "denied_commands": decision.denied_commands,
            "denial_reason": decision.reason,
            "needed_commands": decision.needed_commands,
            "tester_disallow_dangerous_commands": policy.disallow_dangerous_commands,
            "tester_denied_commands": policy.deny_commands,
        },
    )


def _checker_source(value: object, task_id: str) -> str:
    if value in {"pytest", "script"}:
        return str(value)
    raise ConfigError(f"terminal_task task {task_id!r} requires checker.source as 'pytest' or 'script'")


def _checker_path(value: object, task_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"terminal_task task {task_id!r} requires checker.path as a non-empty string")
    if "\\" in value:
        raise ConfigError(f"terminal_task task {task_id!r} checker.path may not contain backslashes")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) in ("", "."):
        raise ConfigError(f"terminal_task task {task_id!r} checker.path must be a safe relative path")
    return str(path)


def _optional_positive_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    raise ConfigError(f"{field} must be a positive number")


def _manifest_dir(task: SecureBenchTask) -> Path:
    metadata = task.metadata if isinstance(task.metadata, dict) else {}
    pack = metadata.get("benchmark_pack")
    manifest_path = pack.get("manifest_path") if isinstance(pack, dict) else None
    if not isinstance(manifest_path, str) or not manifest_path:
        raise ConfigError("terminal_task checker.path requires benchmark_pack.manifest_path metadata")
    return Path(manifest_path).parent.resolve()


def _eval_asset_root(task: SecureBenchTask, manifest_dir: Path) -> Path:
    metadata = task.metadata if isinstance(task.metadata, dict) else {}
    roots = metadata.get("asset_roots")
    root_value = roots.get("eval") if isinstance(roots, dict) else "hidden/"
    if not isinstance(root_value, str) or not root_value:
        raise ConfigError("terminal_task asset_roots.eval must be a non-empty string")
    if "\\" in root_value:
        raise ConfigError("terminal_task asset_roots.eval may not contain backslashes")
    root_path = PurePosixPath(root_value)
    if root_path.is_absolute() or ".." in root_path.parts or str(root_path) in ("", "."):
        raise ConfigError("terminal_task asset_roots.eval must be a safe relative path")
    root = (manifest_dir / root_value).resolve()
    if not root.is_relative_to(manifest_dir):
        raise ConfigError("terminal_task asset_roots.eval may not escape benchmark package")
    return root


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


_PYTEST_COMPAT_RUNNER = r"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import subprocess
import sys
import traceback


target = pathlib.Path(os.environ["SECUREBENCH_CHECKER_TARGET"])

if importlib.util.find_spec("pytest") is not None:
    raise SystemExit(subprocess.run([sys.executable, "-m", "pytest", str(target), "-rA"], check=False).returncode)


def test_files(path: pathlib.Path) -> list[pathlib.Path]:
    if path.is_file():
        return [path]
    return sorted(path.rglob("test_*.py"))


failures = 0
for index, file_path in enumerate(test_files(target)):
    module_name = f"securebench_terminal_check_{index}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        print(f"could not load checker file: {file_path}", file=sys.stderr)
        failures += 1
        continue
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except BaseException:
        traceback.print_exc()
        failures += 1
        continue
    for name in sorted(vars(module)):
        value = getattr(module, name)
        if name.startswith("test_") and callable(value):
            try:
                value()
            except BaseException:
                traceback.print_exc()
                failures += 1

raise SystemExit(1 if failures else 0)
""".strip()


def _close_sandbox(sandbox: Sandbox) -> None:
    close = getattr(sandbox, "close", None)
    if callable(close):
        close()
