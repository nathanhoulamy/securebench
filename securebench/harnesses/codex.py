"""Codex harness implementation."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from securebench.candidates.extraction import (
    default_extraction_spec,
    extract_candidate,
    extraction_instructions,
)
from securebench.candidates import CandidateArtifact, CandidateProducer
from securebench.errors import ConfigError
from securebench.harnesses.shared import (
    agent_task_json,
    close_sandbox,
    container_workspace_path,
    container_image_for_task,
    optional_positive_number,
    materialize_workdir_from_image_if_requested,
    reject_task_file_collision,
    reject_unknown_fields,
    run_timeout_seconds,
    task_workdir,
    workspace_path,
    workspace_mount_target_for_task,
    workspace_root,
)
from securebench.harnesses.network import (
    allowed_domains_config,
    docker_egress_policy,
    effective_allowed_domains,
)
from securebench.workspaces.materialization import VisibilityAwareMaterializer, docker_read_only_mounts
from securebench.sandboxes import DockerSandbox, HostSandbox
from securebench.sandboxes.docker import DockerBindMount
from securebench.tasks import SecureBenchTask


CODEX_CONFIG_FIELDS = {
    "model",
    "version",
    "task_file",
    "timeout_seconds",
    "allowed_domains",
}
CODEX_OVERLAY_TARGET = "/opt/securebench/codex"
CODEX_HOME_TARGET = "/opt/securebench/codex-home"
CODEX_DEFAULT_VERSION = "latest"
CODEX_DEFAULT_TASK_FILE = "task.json"
CODEX_DEFAULT_TIMEOUT_SECONDS = 900.0
CODEX_RUNTIME_NODE_IMAGE = "node:22-bookworm"


@dataclass(frozen=True)
class DockerPlatform:
    os: str
    architecture: str
    variant: str | None = None

    @property
    def cache_key(self) -> str:
        if self.variant:
            return f"{self.os}-{self.architecture}-{self.variant}"
        return f"{self.os}-{self.architecture}"

    @property
    def docker_platform(self) -> str:
        if self.variant:
            return f"{self.os}/{self.architecture}/{self.variant}"
        return f"{self.os}/{self.architecture}"


@dataclass(frozen=True)
class CodexOverlay:
    path: Path
    platform: DockerPlatform
    version: str


class CodexHarnessProducer(CandidateProducer):
    """Run Codex CLI in the benchmark environment with a mounted tooling overlay."""

    def __init__(
        self,
        *,
        model: str,
        env_names: tuple[str, ...] = (),
        version: str = CODEX_DEFAULT_VERSION,
        task_file: str = CODEX_DEFAULT_TASK_FILE,
        timeout_seconds: float | None = CODEX_DEFAULT_TIMEOUT_SECONDS,
        allowed_domains: tuple[str, ...] = (),
        workspace_root: str | Path | None = None,
    ) -> None:
        self.model = model
        self.env_names = codex_env_names(env_names)
        self.version = codex_version(version)
        self.task_file = task_file
        self.timeout_seconds = timeout_seconds
        self.allowed_domains = tuple(allowed_domains)
        self.workspace_root = None if workspace_root is None else Path(workspace_root)
        self.materializer = VisibilityAwareMaterializer()

    def produce(self, task: SecureBenchTask, **context: Any) -> CandidateArtifact:
        image = container_image_for_task(task)
        require_env_names(self.env_names, "codex")
        task_workspace = workspace_root(
            task,
            context.get("workspace_root", self.workspace_root),
        )
        cleanup = None
        if task_workspace is None:
            cleanup = tempfile.TemporaryDirectory(prefix="securebench-codex-")
            task_workspace = Path(cleanup.name)
        state_cleanup = None

        try:
            task_workspace.mkdir(parents=True, exist_ok=True)
            materialize_workdir_from_image_if_requested(task, task_workspace)
            state_cleanup = tempfile.TemporaryDirectory(prefix="securebench-codex-home-")
            state_root = Path(state_cleanup.name)
            staging = HostSandbox(root=task_workspace)
            plan = self.materializer.materialize(task, staging, "agent")
            reject_task_file_collision(self.task_file, plan)
            staging.write_file(self.task_file, agent_task_json(task))

            overlay = codex_overlay_for_image(image, self.version)
            workspace_mount_target = workspace_mount_target_for_task(task)
            allowed_domains = effective_allowed_domains("codex", self.allowed_domains)
            with docker_egress_policy(allowed_domains) as egress:
                sandbox = DockerSandbox(
                    image=image,
                    root=task_workspace,
                    env_names=self.env_names,
                    env=egress.env,
                    network=egress.network,
                    read_only=False,
                    mounts=(
                        *docker_read_only_mounts(plan, task_workspace),
                        DockerBindMount(
                            source=overlay.path,
                            target=CODEX_OVERLAY_TARGET,
                            read_only=True,
                        ),
                        DockerBindMount(
                            source=state_root,
                            target=CODEX_HOME_TARGET,
                            read_only=False,
                        ),
                    ),
                    workspace_mount_target=workspace_mount_target,
                )
                try:
                    timeout = run_timeout_seconds(
                        task,
                        context_timeout=context.get("timeout"),
                        fallback_timeout=self.timeout_seconds,
                    )
                    preflight = sandbox.run(
                        codex_shell_command("codex --version"),
                        timeout=timeout,
                    )
                    if preflight.exit_code != 0:
                        raise ConfigError(
                            "codex overlay is incompatible with benchmark environment image "
                            f"{image!r}: codex --version failed with exit code {preflight.exit_code}; "
                            f"stderr: {preflight.stderr.strip()}"
                        )
                    task_file_for_agent = container_workspace_path(
                        self.task_file,
                        mount_target=workspace_mount_target,
                    )
                    agent_workdir = codex_agent_workdir(task)
                    baseline = prepare_repo_patch_baseline(
                        sandbox,
                        task,
                        agent_workdir,
                        timeout,
                    )
                    result = sandbox.run(
                        codex_shell_command(
                            f"codex exec --model {shell_quote(self.model)} --json --skip-git-repo-check "
                            f"--dangerously-bypass-approvals-and-sandbox "
                            f"{shell_quote(codex_prompt(task, task_file_for_agent))}"
                        ),
                        workdir=agent_workdir,
                        timeout=timeout,
                    )
                    extraction = default_extraction_spec(task)
                    candidate = extract_candidate(
                        sandbox,
                        result,
                        extraction,
                        timeout=timeout,
                    )
                    return CandidateArtifact(
                        patch=candidate.patch,
                        workspace=candidate.workspace,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        metadata={
                            "harness": "codex",
                            "exit_code": result.exit_code,
                            "task_file": self.task_file,
                            "workspace_root": str(task_workspace),
                            "benchmark_environment_image": image,
                            "codex_version": overlay.version,
                            "codex_model": self.model,
                            "overlay_platform": overlay.platform.docker_platform,
                            "overlay_cache_path": str(overlay.path),
                            "allowed_domains": allowed_domains,
                            **baseline,
                            **candidate.metadata,
                        },
                    )
                finally:
                    close_sandbox(sandbox)
        finally:
            if state_cleanup is not None:
                state_cleanup.cleanup()
            if cleanup is not None:
                cleanup.cleanup()


def codex_config(config: dict[str, Any]) -> dict[str, Any]:
    reject_unknown_fields(config, CODEX_CONFIG_FIELDS, "harness.config")
    return {
        "model": codex_model(config.get("model")),
        "version": codex_version(config.get("version", CODEX_DEFAULT_VERSION)),
        "task_file": workspace_path(
            config.get("task_file", CODEX_DEFAULT_TASK_FILE),
            "harness.config.task_file",
        ),
        "timeout_seconds": optional_positive_number(
            config.get("timeout_seconds", CODEX_DEFAULT_TIMEOUT_SECONDS),
            "harness.config.timeout_seconds",
        ),
        "allowed_domains": allowed_domains_config(config.get("allowed_domains")),
    }


def codex_env_names(env_names: tuple[str, ...]) -> tuple[str, ...]:
    names = tuple(env_names)
    if "OPENAI_API_KEY" not in names:
        names = (*names, "OPENAI_API_KEY")
    return names


def require_env_names(env_names: tuple[str, ...], harness: str) -> None:
    missing = [name for name in env_names if not os.environ.get(name)]
    if missing:
        raise ConfigError(
            f"{harness} harness requires environment variable(s): {', '.join(missing)}"
        )


def codex_version(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("harness.config.version must be a non-empty string")
    version = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", version):
        raise ConfigError("harness.config.version contains unsupported characters")
    return version


def codex_model(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("harness.config.model must be a non-empty string")
    model = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", model):
        raise ConfigError("harness.config.model contains unsupported characters")
    return model


def codex_overlay_for_image(image: str, version: str) -> CodexOverlay:
    platform = docker_image_platform(image)
    overlay_path = codex_overlay_cache_root() / "codex" / version / platform.cache_key
    codex_binary = overlay_path / "bin" / "codex"
    node_binary = overlay_path / "bin" / "node"
    if not codex_binary.exists() or not node_binary.exists():
        populate_codex_overlay_cache(overlay_path, version, platform)
    if not codex_binary.exists():
        raise ConfigError(f"Codex overlay cache did not produce expected binary: {codex_binary}")
    if not node_binary.exists():
        raise ConfigError(f"Codex overlay cache did not produce expected Node runtime: {node_binary}")
    return CodexOverlay(path=overlay_path, platform=platform, version=version)


def codex_overlay_cache_root() -> Path:
    return Path(
        os.environ.get(
            "SECUREBENCH_AGENT_CACHE",
            Path.home() / ".cache" / "securebench" / "agents",
        )
    )


def docker_image_platform(image: str) -> DockerPlatform:
    inspect = run_docker(["docker", "image", "inspect", image])
    if inspect.returncode != 0:
        pull = run_docker(["docker", "pull", image])
        if pull.returncode != 0:
            raise ConfigError(
                f"Failed to pull benchmark environment image {image!r}: {pull.stderr.strip()}"
            )
        inspect = run_docker(["docker", "image", "inspect", image])
    if inspect.returncode != 0:
        raise ConfigError(
            f"Failed to inspect benchmark environment image {image!r}: {inspect.stderr.strip()}"
        )
    try:
        data = json.loads(inspect.stdout)
        image_data = data[0] if isinstance(data, list) and data else {}
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Failed to parse Docker inspect output for {image!r}") from exc
    os_name = normalize_docker_os(image_data.get("Os"))
    architecture = normalize_docker_architecture(image_data.get("Architecture"))
    variant = normalize_docker_variant(image_data.get("Variant"))
    return DockerPlatform(os=os_name, architecture=architecture, variant=variant)


def normalize_docker_os(value: Any) -> str:
    if value != "linux":
        raise ConfigError(f"Codex harness requires a linux benchmark image, got {value!r}")
    return value


def normalize_docker_architecture(value: Any) -> str:
    if value in {"amd64", "x86_64"}:
        return "amd64"
    if value in {"arm64", "aarch64"}:
        return "arm64"
    if value == "arm":
        return "arm"
    raise ConfigError(f"Unsupported Docker image architecture for Codex overlay: {value!r}")


def normalize_docker_variant(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and re.fullmatch(r"v[0-9]+", value):
        return value
    raise ConfigError(f"Unsupported Docker image architecture variant for Codex overlay: {value!r}")


def populate_codex_overlay_cache(
    overlay_path: Path, version: str, platform: DockerPlatform
) -> None:
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    cache_root = codex_overlay_cache_root()
    install_prefix = f"/cache/codex/{version}/{platform.cache_key}"
    result = run_docker(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            platform.docker_platform,
            "-v",
            f"{cache_root}:/cache",
            CODEX_RUNTIME_NODE_IMAGE,
            "sh",
            "-lc",
            (
                f"npm install -g @openai/codex@{version} --prefix {install_prefix} && "
                f"cp $(command -v node) {install_prefix}/bin/node && "
                f"chmod +x {install_prefix}/bin/node"
            ),
        ]
    )
    if result.returncode != 0:
        raise ConfigError(f"Failed to populate Codex overlay cache: {result.stderr.strip()}")


def run_docker(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def codex_shell_command(inner: str) -> str:
    return (
        f"export HOME={shell_quote(CODEX_HOME_TARGET)}; "
        f"export PATH={shell_quote(CODEX_OVERLAY_TARGET + '/bin')}:$PATH; "
        'if [ -z "$OPENAI_API_KEY" ] && [ -n "$CODEX_API_KEY" ]; then export OPENAI_API_KEY="$CODEX_API_KEY"; fi; '
        'if [ -z "$CODEX_API_KEY" ] && [ -n "$OPENAI_API_KEY" ]; then export CODEX_API_KEY="$OPENAI_API_KEY"; fi; '
        f"{inner}"
    )


def prepare_repo_patch_baseline(
    sandbox: DockerSandbox,
    task: SecureBenchTask,
    workdir: str | None,
    timeout: float | None,
) -> dict[str, object]:
    """Commit image-provided dirty state so extracted diffs only include agent changes."""
    if task.task_type != "repo_patch" or workdir is None:
        return {}
    status = sandbox.run(["git", "status", "--porcelain=v1"], workdir=workdir, timeout=timeout)
    if status.exit_code != 0:
        raise ConfigError(
            f"failed to inspect repo_patch baseline state for task {task.id!r}: "
            f"{status.stderr.strip()}"
        )
    if not status.stdout.strip():
        return {"repo_patch_baseline": "clean"}
    add = sandbox.run(["git", "add", "-A"], workdir=workdir, timeout=timeout)
    if add.exit_code != 0:
        raise ConfigError(
            f"failed to stage repo_patch baseline state for task {task.id!r}: {add.stderr.strip()}"
        )
    commit = sandbox.run(
        [
            "git",
            "-c",
            "user.name=SecureBench",
            "-c",
            "user.email=securebench@example.invalid",
            "commit",
            "--no-verify",
            "-m",
            "securebench baseline",
        ],
        workdir=workdir,
        timeout=timeout,
    )
    if commit.exit_code != 0:
        raise ConfigError(
            f"failed to commit repo_patch baseline state for task {task.id!r}: "
            f"{commit.stderr.strip()}"
        )
    return {"repo_patch_baseline": "committed"}


def codex_agent_workdir(task: SecureBenchTask) -> str | None:
    """Return the container workdir where Codex should operate."""
    if task.task_type in {"repo_patch", "terminal_task"}:
        return task_workdir(task)
    return None


def codex_prompt(task: SecureBenchTask, task_file: str) -> str:
    extraction = default_extraction_spec(task)
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


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
