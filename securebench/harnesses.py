"""Candidate-producing harnesses for tester YAML runs."""

from __future__ import annotations

import json
import re
import tempfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from securebench.candidates import CandidateArtifact, CandidateProducer
from securebench.errors import ConfigError
from securebench.families import family_contract_for
from securebench.materialization import (
    MaterializationPlan,
    VisibilityAwareMaterializer,
    docker_read_only_mounts,
)
from securebench.path_policy import PathPolicyError, validate_workspace_mount_for_component
from securebench.sandboxes import DockerSandbox, HostSandbox, Sandbox
from securebench.tasks import SecureBenchTask
from securebench.tester_config import TesterHarnessSection


COMMAND_CONFIG_FIELDS = {"command", "artifact_path", "task_file", "timeout_seconds"}


class CommandHarnessProducer(CandidateProducer):
    """Run a tester-provided command against the task's public workspace."""

    def __init__(
        self,
        *,
        mode: str,
        command: str | tuple[str, ...],
        image: str | None = None,
        env_names: tuple[str, ...] = (),
        artifact_path: str | None = None,
        task_file: str = "securebench_task.json",
        timeout_seconds: float | None = None,
        workspace_root: str | Path | None = None,
    ) -> None:
        if mode not in {"host", "container"}:
            raise ConfigError("command harness mode must be 'host' or 'container'")
        if mode == "container" and image is None:
            raise ConfigError("command harness container mode requires an image")
        self.mode = mode
        self.image = image
        self.env_names = tuple(env_names)
        self.command = command
        self.artifact_path = artifact_path
        self.task_file = task_file
        self.timeout_seconds = timeout_seconds
        self.workspace_root = None if workspace_root is None else Path(workspace_root)
        self.materializer = VisibilityAwareMaterializer()

    def produce(self, task: SecureBenchTask, **context: Any) -> CandidateArtifact:
        contract = family_contract_for(task.task_type)
        workspace_root = _workspace_root(
            task,
            context.get("workspace_root", self.workspace_root),
        )
        cleanup = None
        if workspace_root is None:
            cleanup = tempfile.TemporaryDirectory(prefix="securebench-harness-")
            workspace_root = Path(cleanup.name)
        workspace_root.mkdir(parents=True, exist_ok=True)

        try:
            staging = HostSandbox(root=workspace_root)
            plan = self.materializer.materialize(task, staging, "agent")
            _reject_task_file_collision(self.task_file, plan)
            _reject_artifact_collision(self.artifact_path, plan)
            staging.write_file(self.task_file, _agent_task_json(task))

            sandbox = self._sandbox(workspace_root, plan)
            try:
                result = sandbox.run(
                    self.command,
                    timeout=context.get("timeout", self.timeout_seconds),
                )
                raw_candidate = result.stdout
                if self.artifact_path is not None:
                    raw_candidate = sandbox.read_file(self.artifact_path)
                return CandidateArtifact(
                    text=raw_candidate if contract.candidate_kind in {"text", "code"} else None,
                    patch=raw_candidate if contract.candidate_kind == "patch" else None,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    metadata={
                        "harness": "command",
                        "mode": self.mode,
                        "exit_code": result.exit_code,
                        "task_file": self.task_file,
                        "artifact_path": self.artifact_path,
                        "workspace_root": str(workspace_root),
                        "candidate_kind": contract.candidate_kind,
                    },
                )
            finally:
                _close_sandbox(sandbox)
        finally:
            if cleanup is not None:
                cleanup.cleanup()

    def _sandbox(self, workspace_root: Path, plan: MaterializationPlan) -> Sandbox:
        if self.mode == "host":
            return HostSandbox(root=workspace_root, env_names=self.env_names)
        return DockerSandbox(
            image=self.image or "",
            root=workspace_root,
            env_names=self.env_names,
            mounts=docker_read_only_mounts(plan, workspace_root),
        )


def build_harness_producer(
    harness: TesterHarnessSection,
    *,
    workspace_root: str | Path | None = None,
) -> CandidateProducer:
    """Build a candidate producer for one parsed tester harness section."""
    if harness.type == "command":
        config = _command_config(harness.config)
        return CommandHarnessProducer(
            mode=harness.mode,
            image=harness.image,
            env_names=harness.env,
            workspace_root=workspace_root,
            **config,
        )
    raise ConfigError(
        f"Harness type {harness.type!r} is parsed but not implemented yet; "
        "use harness.type 'command' for this refactoring step"
    )


def _command_config(config: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_fields(config, COMMAND_CONFIG_FIELDS, "harness.config")
    return {
        "command": _command_value(config.get("command")),
        "artifact_path": _optional_workspace_path(config.get("artifact_path"), "harness.config.artifact_path"),
        "task_file": _workspace_path(config.get("task_file", "securebench_task.json"), "harness.config.task_file"),
        "timeout_seconds": _optional_positive_number(config.get("timeout_seconds"), "harness.config.timeout_seconds"),
    }


def _command_value(value: Any) -> str | tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, list) and value and all(isinstance(item, str) and item.strip() for item in value):
        return tuple(value)
    raise ConfigError("harness.config.command must be a non-empty string or string array")


def _optional_workspace_path(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _workspace_path(value, field)


def _workspace_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty workspace-relative path")
    try:
        return validate_workspace_mount_for_component("agent", value).path
    except PathPolicyError as exc:
        raise ConfigError(f"{field} is unsafe: {exc}") from exc


def _optional_positive_number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{field} must be a positive number")
    return float(value)


def _reject_unknown_fields(data: dict[str, Any], allowed: set[str], section: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"{section} contains unsupported field(s): {', '.join(unknown)}")


def _workspace_root(task: SecureBenchTask, root: str | Path | None) -> Path | None:
    if root is None:
        return None
    return Path(root) / _workspace_dir_name(task)


def _workspace_dir_name(task: SecureBenchTask) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", task.id).strip("._")
    if cleaned == task.id and cleaned:
        return cleaned
    digest = sha256(task.id.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned or 'task'}-{digest}"


def _agent_task_json(task: SecureBenchTask) -> str:
    return json.dumps(task.agent_payload(), indent=2, sort_keys=True) + "\n"


def _reject_task_file_collision(task_file: str, plan: MaterializationPlan) -> None:
    path = PurePosixPath(task_file)
    for resource in plan.resources:
        if _paths_overlap(path, PurePosixPath(resource.relative_path)):
            raise ConfigError(f"harness.config.task_file collides with public materialized path: {task_file}")


def _reject_artifact_collision(artifact_path: str | None, plan: MaterializationPlan) -> None:
    if artifact_path is None:
        return
    path = PurePosixPath(artifact_path)
    for resource in plan.resources:
        if _paths_overlap(path, PurePosixPath(resource.relative_path)):
            raise ConfigError(f"harness.config.artifact_path collides with public materialized path: {artifact_path}")


def _paths_overlap(left: PurePosixPath, right: PurePosixPath) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _close_sandbox(sandbox: Sandbox) -> None:
    close = getattr(sandbox, "close", None)
    if callable(close):
        close()
