"""Claude Code harness implementation."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from securebench.candidates import CandidateArtifact, CandidateProducer
from securebench.candidates.extraction import (
    default_extraction_spec,
    extract_candidate,
    extraction_instructions,
)
from securebench.errors import ConfigError
from securebench.harnesses.codex import (
    DockerPlatform,
    docker_image_platform,
    prepare_repo_patch_baseline,
    run_docker,
    shell_quote,
)
from securebench.harnesses.shared import (
    agent_task_json,
    close_sandbox,
    container_image_for_task,
    container_workspace_path,
    optional_positive_number,
    reject_task_file_collision,
    reject_unknown_fields,
    task_workdir,
    workspace_mount_target_for_task,
    workspace_path,
    workspace_root,
)
from securebench.sandboxes import DockerSandbox, HostSandbox
from securebench.sandboxes.docker import DockerBindMount
from securebench.tasks import SecureBenchTask
from securebench.workspaces.materialization import (
    VisibilityAwareMaterializer,
    docker_read_only_mounts,
)


CLAUDE_CODE_CONFIG_FIELDS = {"model", "version", "task_file", "timeout_seconds"}
CLAUDE_CODE_OVERLAY_TARGET = "/opt/securebench/claude-code"
CLAUDE_CODE_HOME_TARGET = "/opt/securebench/claude-home"
CLAUDE_CODE_DEFAULT_MODEL = "sonnet"
CLAUDE_CODE_DEFAULT_VERSION = "latest"
CLAUDE_CODE_DEFAULT_TASK_FILE = "task.json"
CLAUDE_CODE_DEFAULT_TIMEOUT_SECONDS = 900.0
CLAUDE_CODE_RUNTIME_NODE_IMAGE = "node:22-bookworm"


@dataclass(frozen=True)
class ClaudeCodeOverlay:
    path: Path
    platform: DockerPlatform
    version: str


class ClaudeCodeHarnessProducer(CandidateProducer):
    """Run Claude Code in the benchmark environment with a mounted tooling overlay."""

    def __init__(
        self,
        *,
        model: str = CLAUDE_CODE_DEFAULT_MODEL,
        env_names: tuple[str, ...] = (),
        version: str = CLAUDE_CODE_DEFAULT_VERSION,
        task_file: str = CLAUDE_CODE_DEFAULT_TASK_FILE,
        timeout_seconds: float | None = CLAUDE_CODE_DEFAULT_TIMEOUT_SECONDS,
        workspace_root: str | Path | None = None,
    ) -> None:
        self.model = claude_code_model(model)
        self.env_names = claude_code_env_names(env_names)
        self.version = claude_code_version(version)
        self.task_file = task_file
        self.timeout_seconds = timeout_seconds
        self.workspace_root = None if workspace_root is None else Path(workspace_root)
        self.materializer = VisibilityAwareMaterializer()

    def produce(self, task: SecureBenchTask, **context: Any) -> CandidateArtifact:
        image = container_image_for_task(task)
        require_env_names(self.env_names, "claude_code")
        task_workspace = workspace_root(
            task,
            context.get("workspace_root", self.workspace_root),
        )
        cleanup = None
        if task_workspace is None:
            cleanup = tempfile.TemporaryDirectory(prefix="securebench-claude-code-")
            task_workspace = Path(cleanup.name)
        task_workspace.mkdir(parents=True, exist_ok=True)
        state_cleanup = tempfile.TemporaryDirectory(prefix="securebench-claude-home-")
        state_root = Path(state_cleanup.name)

        try:
            staging = HostSandbox(root=task_workspace)
            plan = self.materializer.materialize(task, staging, "agent")
            reject_task_file_collision(self.task_file, plan)
            staging.write_file(self.task_file, agent_task_json(task))

            overlay = claude_code_overlay_for_image(image, self.version)
            workspace_mount_target = workspace_mount_target_for_task(task)
            sandbox = DockerSandbox(
                image=image,
                root=task_workspace,
                env_names=self.env_names,
                network="bridge",
                read_only=False,
                mounts=(
                    *docker_read_only_mounts(plan, task_workspace),
                    DockerBindMount(
                        source=overlay.path,
                        target=CLAUDE_CODE_OVERLAY_TARGET,
                        read_only=True,
                    ),
                    DockerBindMount(
                        source=state_root,
                        target=CLAUDE_CODE_HOME_TARGET,
                        read_only=False,
                    ),
                ),
                workspace_mount_target=workspace_mount_target,
            )
            try:
                timeout = context.get("timeout", self.timeout_seconds)
                preflight = sandbox.run(
                    claude_code_shell_command("claude --version"),
                    timeout=timeout,
                )
                if preflight.exit_code != 0:
                    raise ConfigError(
                        "claude_code overlay is incompatible with benchmark environment image "
                        f"{image!r}: claude --version failed with exit code {preflight.exit_code}; "
                        f"stderr: {preflight.stderr.strip()}"
                    )
                task_file_for_agent = container_workspace_path(
                    self.task_file,
                    mount_target=workspace_mount_target,
                )
                agent_workdir = claude_code_agent_workdir(task)
                baseline = prepare_repo_patch_baseline(sandbox, task, agent_workdir, timeout)
                result = sandbox.run(
                    claude_code_shell_command(
                        f"claude -p --model {shell_quote(self.model)} "
                        "--output-format json --dangerously-skip-permissions "
                        "--no-session-persistence "
                        f"{shell_quote(claude_code_prompt(task, task_file_for_agent))}"
                    ),
                    workdir=agent_workdir,
                    timeout=timeout,
                )
                extraction = default_extraction_spec(task, allow_stdout=False)
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
                    stdout=result.stdout,
                    stderr=result.stderr,
                    metadata={
                        "harness": "claude_code",
                        "exit_code": result.exit_code,
                        "task_file": self.task_file,
                        "workspace_root": str(task_workspace),
                        "benchmark_environment_image": image,
                        "claude_code_version": overlay.version,
                        "claude_code_model": self.model,
                        "overlay_platform": overlay.platform.docker_platform,
                        "overlay_cache_path": str(overlay.path),
                        **baseline,
                        **candidate.metadata,
                    },
                )
            finally:
                close_sandbox(sandbox)
        finally:
            state_cleanup.cleanup()
            if cleanup is not None:
                cleanup.cleanup()


def claude_code_config(config: dict[str, Any]) -> dict[str, Any]:
    reject_unknown_fields(config, CLAUDE_CODE_CONFIG_FIELDS, "harness.config")
    return {
        "model": claude_code_model(config.get("model", CLAUDE_CODE_DEFAULT_MODEL)),
        "version": claude_code_version(config.get("version", CLAUDE_CODE_DEFAULT_VERSION)),
        "task_file": workspace_path(
            config.get("task_file", CLAUDE_CODE_DEFAULT_TASK_FILE),
            "harness.config.task_file",
        ),
        "timeout_seconds": optional_positive_number(
            config.get("timeout_seconds", CLAUDE_CODE_DEFAULT_TIMEOUT_SECONDS),
            "harness.config.timeout_seconds",
        ),
    }


def claude_code_env_names(env_names: tuple[str, ...]) -> tuple[str, ...]:
    names = tuple(env_names)
    if "ANTHROPIC_API_KEY" not in names:
        names = (*names, "ANTHROPIC_API_KEY")
    return names


def require_env_names(env_names: tuple[str, ...], harness: str) -> None:
    missing = [name for name in env_names if not os.environ.get(name)]
    if missing:
        raise ConfigError(
            f"{harness} harness requires environment variable(s): {', '.join(missing)}"
        )


def claude_code_version(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("harness.config.version must be a non-empty string")
    version = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", version):
        raise ConfigError("harness.config.version contains unsupported characters")
    return version


def claude_code_model(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("harness.config.model must be a non-empty string")
    model = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", model):
        raise ConfigError("harness.config.model contains unsupported characters")
    return model


def claude_code_overlay_for_image(image: str, version: str) -> ClaudeCodeOverlay:
    platform = docker_image_platform(image)
    overlay_path = (
        claude_code_overlay_cache_root()
        / "claude-code"
        / version
        / platform.cache_key
    )
    claude_binary = overlay_path / "bin" / "claude"
    node_binary = overlay_path / "bin" / "node"
    if not claude_binary.exists() or not node_binary.exists():
        populate_claude_code_overlay_cache(overlay_path, version, platform)
    if not claude_binary.exists():
        raise ConfigError(
            f"Claude Code overlay cache did not produce expected binary: {claude_binary}"
        )
    if not node_binary.exists():
        raise ConfigError(
            f"Claude Code overlay cache did not produce expected Node runtime: {node_binary}"
        )
    return ClaudeCodeOverlay(path=overlay_path, platform=platform, version=version)


def claude_code_overlay_cache_root() -> Path:
    return Path(
        os.environ.get(
            "SECUREBENCH_AGENT_CACHE",
            Path.home() / ".cache" / "securebench" / "agents",
        )
    )


def populate_claude_code_overlay_cache(
    overlay_path: Path, version: str, platform: DockerPlatform
) -> None:
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    cache_root = claude_code_overlay_cache_root()
    install_prefix = f"/cache/claude-code/{version}/{platform.cache_key}"
    result = run_docker(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            platform.docker_platform,
            "-v",
            f"{cache_root}:/cache",
            CLAUDE_CODE_RUNTIME_NODE_IMAGE,
            "sh",
            "-lc",
            (
                f"npm install -g @anthropic-ai/claude-code@{version} --prefix {install_prefix} && "
                f"cp $(command -v node) {install_prefix}/bin/node && "
                f"chmod +x {install_prefix}/bin/node"
            ),
        ]
    )
    if result.returncode != 0:
        raise ConfigError(f"Failed to populate Claude Code overlay cache: {result.stderr.strip()}")


def claude_code_shell_command(inner: str) -> str:
    return (
        f"export HOME={shell_quote(CLAUDE_CODE_HOME_TARGET)}; "
        f"export PATH={shell_quote(CLAUDE_CODE_OVERLAY_TARGET + '/bin')}:$PATH; "
        f"{inner}"
    )


def claude_code_agent_workdir(task: SecureBenchTask) -> str | None:
    if task.task_type in {"repo_patch", "terminal_task"}:
        return task_workdir(task)
    return None


def claude_code_prompt(task: SecureBenchTask, task_file: str) -> str:
    extraction = default_extraction_spec(task, allow_stdout=False)
    if task.task_type == "repo_patch":
        return (
            f"Read {task_file} and solve the benchmark task using only public workspace data. "
            "The repository checkout to edit is the current working directory. "
            "Do not clone the repository. "
            "Edit only the implementation files needed for the fix; do not edit tests, "
            "evaluation files, dependency files, lock files, or build configuration unless the "
            "task explicitly requires those files. "
            f"{extraction_instructions(extraction)}"
        )
    base = f"Read {task_file} and solve the benchmark task using only public workspace data."
    return f"{base} {extraction_instructions(extraction)}"
