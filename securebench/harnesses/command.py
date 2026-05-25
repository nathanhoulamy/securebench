"""Command harness implementation."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from securebench.candidates.extraction import (
    default_extraction_spec,
    extract_candidate,
    file_extraction_spec,
    stdout_extraction_spec,
)
from securebench.candidates import CandidateArtifact, CandidateProducer
from securebench.errors import ConfigError
from securebench.harnesses.shared import (
    agent_task_json,
    close_sandbox,
    container_image_for_task,
    optional_positive_number,
    optional_workspace_path,
    reject_artifact_collision,
    reject_task_file_collision,
    reject_unknown_fields,
    run_timeout_seconds,
    task_workdir,
    workspace_path,
    workspace_mount_target_for_task,
    workspace_root,
)
from securebench.harnesses.network import (
    HarnessEgress,
    allowed_domains_config,
    docker_egress_policy,
    effective_allowed_domains,
)
from securebench.workspaces.materialization import (
    MaterializationPlan,
    VisibilityAwareMaterializer,
    docker_read_only_mounts,
)
from securebench.sandboxes import DockerSandbox, HostSandbox, Sandbox
from securebench.tasks import SecureBenchTask


COMMAND_CONFIG_FIELDS = {
    "command",
    "artifact_path",
    "task_file",
    "timeout_seconds",
    "allowed_domains",
}
COMMAND_DEFAULT_TASK_FILE = "task.json"


class CommandHarnessProducer(CandidateProducer):
    """Run a tester-provided command against the task's public workspace."""

    def __init__(
        self,
        *,
        command: str | tuple[str, ...],
        env_names: tuple[str, ...] = (),
        artifact_path: str | None = None,
        task_file: str = COMMAND_DEFAULT_TASK_FILE,
        timeout_seconds: float | None = None,
        allowed_domains: tuple[str, ...] = (),
        workspace_root: str | Path | None = None,
    ) -> None:
        self.env_names = tuple(env_names)
        self.command = command
        self.artifact_path = artifact_path
        self.task_file = task_file
        self.timeout_seconds = timeout_seconds
        self.allowed_domains = tuple(allowed_domains)
        self.workspace_root = None if workspace_root is None else Path(workspace_root)
        self.materializer = VisibilityAwareMaterializer()

    def produce(self, task: SecureBenchTask, **context: Any) -> CandidateArtifact:
        task_workspace = workspace_root(
            task,
            context.get("workspace_root", self.workspace_root),
        )
        cleanup = None
        if task_workspace is None:
            cleanup = tempfile.TemporaryDirectory(prefix="securebench-harness-")
            task_workspace = Path(cleanup.name)
        task_workspace.mkdir(parents=True, exist_ok=True)

        try:
            staging = HostSandbox(root=task_workspace)
            plan = self.materializer.materialize(task, staging, "agent")
            reject_task_file_collision(self.task_file, plan)
            reject_artifact_collision(self.artifact_path, plan)
            staging.write_file(self.task_file, agent_task_json(task))

            allowed_domains = effective_allowed_domains("command", self.allowed_domains)
            with docker_egress_policy(allowed_domains) as egress:
                sandbox = self._sandbox(task, task_workspace, plan, egress)
                try:
                    timeout = run_timeout_seconds(
                        task,
                        context_timeout=context.get("timeout"),
                        fallback_timeout=self.timeout_seconds,
                    )
                    result = sandbox.run(
                        self.command,
                        workdir=task_workdir(task) if task.task_type == "terminal_task" else None,
                        timeout=timeout,
                    )
                    extraction = (
                        file_extraction_spec(task, self.artifact_path)
                        if self.artifact_path is not None
                        else _default_command_extraction_spec(task)
                    )
                    candidate = extract_candidate(
                        task,
                        sandbox,
                        result,
                        extraction,
                        timeout=timeout,
                    )
                    return CandidateArtifact(
                        text=candidate.text,
                        patch=candidate.patch,
                        workspace=candidate.workspace,
                        stdout=candidate.stdout,
                        stderr=candidate.stderr,
                        metadata={
                            "harness": "command",
                            "exit_code": result.exit_code,
                            "task_file": self.task_file,
                            "artifact_path": self.artifact_path,
                            "workspace_root": str(task_workspace),
                            "allowed_domains": allowed_domains,
                            **candidate.metadata,
                        },
                    )
                finally:
                    close_sandbox(sandbox)
        finally:
            if cleanup is not None:
                cleanup.cleanup()

    def _sandbox(
        self,
        task: SecureBenchTask,
        task_workspace: Path,
        plan: MaterializationPlan,
        egress: HarnessEgress,
    ) -> Sandbox:
        image = container_image_for_task(task)
        return DockerSandbox(
            image=image,
            root=task_workspace,
            env_names=self.env_names,
            env=egress.env,
            network=egress.network,
            mounts=docker_read_only_mounts(plan, task_workspace),
            workspace_mount_target=workspace_mount_target_for_task(task),
        )


def command_config(config: dict[str, Any]) -> dict[str, Any]:
    reject_unknown_fields(config, COMMAND_CONFIG_FIELDS, "harness.config")
    return {
        "command": command_value(config.get("command")),
        "artifact_path": optional_workspace_path(
            config.get("artifact_path"), "harness.config.artifact_path"
        ),
        "task_file": workspace_path(
            config.get("task_file", COMMAND_DEFAULT_TASK_FILE),
            "harness.config.task_file",
        ),
        "timeout_seconds": optional_positive_number(
            config.get("timeout_seconds"), "harness.config.timeout_seconds"
        ),
        "allowed_domains": allowed_domains_config(config.get("allowed_domains")),
    }


def command_value(value: Any) -> str | tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return value
    if (
        isinstance(value, list)
        and value
        and all(isinstance(item, str) and item.strip() for item in value)
    ):
        return tuple(value)
    raise ConfigError("harness.config.command must be a non-empty string or string array")


def _default_command_extraction_spec(task: SecureBenchTask):
    if task.task_type == "terminal_task":
        return default_extraction_spec(task)
    return stdout_extraction_spec(task)
