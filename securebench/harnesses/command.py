"""Command harness implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from securebench.candidates.extraction import (
    default_extraction_spec,
    extract_candidate,
)
from securebench.candidates import CandidateProducer, CandidateProduction
from securebench.errors import ConfigError
from securebench.execution_profiles import validate_executable_task
from securebench.harnesses.shared import (
    agent_task_json,
    close_sandbox,
    container_image_for_task,
    materialize_image_workdir,
    optional_positive_number,
    reject_git_patch_framework_collisions,
    reject_task_file_collision,
    reject_unknown_fields,
    run_timeout_seconds,
    task_allowed_domains,
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
    docker_resource_mounts,
)
from securebench.sandboxes import DockerSandbox, HostSandbox, Sandbox
from securebench.tasks import BenchmarkTask


COMMAND_CONFIG_FIELDS = {
    "command",
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
        task_file: str = COMMAND_DEFAULT_TASK_FILE,
        timeout_seconds: float | None = None,
        allowed_domains: tuple[str, ...] = (),
        workspace_root: str | Path | None = None,
    ) -> None:
        self.env_names = tuple(env_names)
        self.command = command
        self.task_file = task_file
        self.timeout_seconds = timeout_seconds
        self.allowed_domains = tuple(allowed_domains)
        self.workspace_root = None if workspace_root is None else Path(workspace_root)
        self.materializer = VisibilityAwareMaterializer()

    def produce(self, task: BenchmarkTask, **context: Any) -> CandidateProduction:
        validate_executable_task(task)
        task_workspace = workspace_root(
            task,
            context.get("workspace_root", self.workspace_root),
        )
        if task_workspace is None:
            raise ConfigError(
                "Command harness requires a persistent workspace_root for stopped-state capture"
            )

        task_workspace.mkdir(parents=True, exist_ok=True)
        materialize_image_workdir(task, task_workspace)
        reject_git_patch_framework_collisions(
            task,
            task_workspace,
            task_file=self.task_file,
        )
        staging = HostSandbox(root=task_workspace)
        plan = self.materializer.materialize(task, staging, "agent")
        reject_task_file_collision(
            self.task_file,
            plan,
            workspace_mount_target=workspace_mount_target_for_task(task),
        )
        staging.write_file(self.task_file, agent_task_json(task))

        allowed_domains = task_allowed_domains(
            task,
            effective_allowed_domains("command", self.allowed_domains),
        )
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
                    workdir=task_workdir(task),
                    timeout=timeout,
                )
                extraction = default_extraction_spec(task)
                candidate = extract_candidate(
                    sandbox,
                    result,
                    extraction,
                    timeout=timeout,
                )
                return CandidateProduction(
                    workspace=candidate.workspace,
                    stdout=candidate.stdout,
                    stderr=candidate.stderr,
                    metadata={
                        "harness": "command",
                        "exit_code": result.exit_code,
                        "task_file": self.task_file,
                        "workspace_root": str(task_workspace),
                        "allowed_domains": allowed_domains,
                        **candidate.metadata,
                    },
                )
            finally:
                close_sandbox(sandbox)

    def _sandbox(
        self,
        task: BenchmarkTask,
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
            mounts=docker_resource_mounts(plan),
            workspace_mount_target=workspace_mount_target_for_task(task),
        )


def command_config(config: dict[str, Any]) -> dict[str, Any]:
    reject_unknown_fields(config, COMMAND_CONFIG_FIELDS, "harness.config")
    return {
        "command": command_value(config.get("command")),
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
