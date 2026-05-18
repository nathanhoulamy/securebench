"""Candidate-producing harnesses for tester YAML runs."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from securebench.candidate_extraction import (
    default_extraction_spec,
    extract_candidate,
    extraction_instructions,
    file_extraction_spec,
    stdout_extraction_spec,
)
from securebench.candidates import CandidateArtifact, CandidateProducer
from securebench.errors import ConfigError
from securebench.materialization import (
    MaterializationPlan,
    VisibilityAwareMaterializer,
    docker_read_only_mounts,
)
from securebench.path_policy import PathPolicyError, validate_workspace_mount_for_component
from securebench.sandboxes import DockerSandbox, HostSandbox, Sandbox
from securebench.sandboxes.docker import DockerBindMount
from securebench.tasks import SecureBenchTask
from securebench.tester_config import TesterHarnessSection


COMMAND_CONFIG_FIELDS = {"command", "artifact_path", "task_file", "timeout_seconds"}
CODEX_CONFIG_FIELDS = {"model", "version", "task_file", "timeout_seconds"}
CODEX_OVERLAY_TARGET = "/opt/securebench/codex"
CODEX_HOME_TARGET = "/opt/securebench/codex-home"
CODEX_DEFAULT_VERSION = "latest"
CODEX_DEFAULT_TASK_FILE = "task.json"
CODEX_DEFAULT_TIMEOUT_SECONDS = 900.0


class CommandHarnessProducer(CandidateProducer):
    """Run a tester-provided command against the task's public workspace."""

    def __init__(
        self,
        *,
        mode: str,
        command: str | tuple[str, ...],
        env_names: tuple[str, ...] = (),
        artifact_path: str | None = None,
        task_file: str = "securebench_task.json",
        timeout_seconds: float | None = None,
        workspace_root: str | Path | None = None,
    ) -> None:
        if mode not in {"host", "container"}:
            raise ConfigError("command harness mode must be 'host' or 'container'")
        self.mode = mode
        self.env_names = tuple(env_names)
        self.command = command
        self.artifact_path = artifact_path
        self.task_file = task_file
        self.timeout_seconds = timeout_seconds
        self.workspace_root = None if workspace_root is None else Path(workspace_root)
        self.materializer = VisibilityAwareMaterializer()

    def produce(self, task: SecureBenchTask, **context: Any) -> CandidateArtifact:
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

            sandbox = self._sandbox(task, workspace_root, plan)
            try:
                result = sandbox.run(
                    self.command,
                    timeout=context.get("timeout", self.timeout_seconds),
                )
                extraction = (
                    file_extraction_spec(task, self.artifact_path)
                    if self.artifact_path is not None
                    else stdout_extraction_spec(task)
                )
                candidate = extract_candidate(
                    task,
                    sandbox,
                    result,
                    extraction,
                    timeout=context.get("timeout", self.timeout_seconds),
                )
                return CandidateArtifact(
                    text=candidate.text,
                    patch=candidate.patch,
                    stdout=candidate.stdout,
                    stderr=candidate.stderr,
                    metadata={
                        "harness": "command",
                        "mode": self.mode,
                        "exit_code": result.exit_code,
                        "task_file": self.task_file,
                        "artifact_path": self.artifact_path,
                        "workspace_root": str(workspace_root),
                        **candidate.metadata,
                    },
                )
            finally:
                _close_sandbox(sandbox)
        finally:
            if cleanup is not None:
                cleanup.cleanup()

    def _sandbox(self, task: SecureBenchTask, workspace_root: Path, plan: MaterializationPlan) -> Sandbox:
        if self.mode == "host":
            return HostSandbox(root=workspace_root, env_names=self.env_names)
        image = _container_image_for_task(task)
        return DockerSandbox(
            image=image,
            root=workspace_root,
            env_names=self.env_names,
            mounts=docker_read_only_mounts(plan, workspace_root),
        )


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
        mode: str,
        model: str,
        env_names: tuple[str, ...] = (),
        version: str = CODEX_DEFAULT_VERSION,
        task_file: str = CODEX_DEFAULT_TASK_FILE,
        timeout_seconds: float | None = CODEX_DEFAULT_TIMEOUT_SECONDS,
        workspace_root: str | Path | None = None,
    ) -> None:
        if mode != "mounted":
            raise ConfigError("codex harness mode must be 'mounted' for this implementation")
        self.mode = mode
        self.model = model
        self.env_names = _codex_env_names(env_names)
        self.version = _codex_version(version)
        self.task_file = task_file
        self.timeout_seconds = timeout_seconds
        self.workspace_root = None if workspace_root is None else Path(workspace_root)
        self.materializer = VisibilityAwareMaterializer()

    def produce(self, task: SecureBenchTask, **context: Any) -> CandidateArtifact:
        image = _container_image_for_task(task)
        _require_env_names(self.env_names, "codex")
        workspace_root = _workspace_root(
            task,
            context.get("workspace_root", self.workspace_root),
        )
        cleanup = None
        if workspace_root is None:
            cleanup = tempfile.TemporaryDirectory(prefix="securebench-codex-")
            workspace_root = Path(cleanup.name)
        workspace_root.mkdir(parents=True, exist_ok=True)
        state_cleanup = tempfile.TemporaryDirectory(prefix="securebench-codex-home-")
        state_root = Path(state_cleanup.name)

        try:
            staging = HostSandbox(root=workspace_root)
            plan = self.materializer.materialize(task, staging, "agent")
            _reject_task_file_collision(self.task_file, plan)
            staging.write_file(self.task_file, _agent_task_json(task))

            overlay = _codex_overlay_for_image(image, self.version)
            sandbox = DockerSandbox(
                image=image,
                root=workspace_root,
                env_names=self.env_names,
                network="bridge",
                mounts=(
                    *docker_read_only_mounts(plan, workspace_root),
                    DockerBindMount(source=overlay.path, target=CODEX_OVERLAY_TARGET, read_only=True),
                    DockerBindMount(source=state_root, target=CODEX_HOME_TARGET, read_only=False),
                ),
            )
            try:
                preflight = sandbox.run(
                    _codex_shell_command("codex --version"),
                    timeout=context.get("timeout", self.timeout_seconds),
                )
                if preflight.exit_code != 0:
                    raise ConfigError(
                        "codex mounted overlay is incompatible with benchmark environment image "
                        f"{image!r}: codex --version failed with exit code {preflight.exit_code}; "
                        f"stderr: {preflight.stderr.strip()}"
                    )
                result = sandbox.run(
                    _codex_shell_command(
                        f"codex exec --model {_shell_quote(self.model)} --json --skip-git-repo-check "
                        f"--dangerously-bypass-approvals-and-sandbox "
                        f"{_shell_quote(_codex_prompt(task, self.task_file))}"
                    ),
                    timeout=context.get("timeout", self.timeout_seconds),
                )
                extraction = default_extraction_spec(task, allow_stdout=False)
                candidate = extract_candidate(
                    task,
                    sandbox,
                    result,
                    extraction,
                    timeout=context.get("timeout", self.timeout_seconds),
                )
                return CandidateArtifact(
                    text=candidate.text,
                    patch=candidate.patch,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    metadata={
                        "harness": "codex",
                        "mode": self.mode,
                        "exit_code": result.exit_code,
                        "task_file": self.task_file,
                        "workspace_root": str(workspace_root),
                        "benchmark_environment_image": image,
                        "codex_version": overlay.version,
                        "codex_model": self.model,
                        "overlay_mode": "mounted",
                        "overlay_platform": overlay.platform.docker_platform,
                        "overlay_cache_path": str(overlay.path),
                        **candidate.metadata,
                    },
                )
            finally:
                _close_sandbox(sandbox)
        finally:
            state_cleanup.cleanup()
            if cleanup is not None:
                cleanup.cleanup()


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
            env_names=harness.env,
            workspace_root=workspace_root,
            **config,
        )
    if harness.type == "codex":
        config = _codex_config(harness.config)
        return CodexHarnessProducer(
            mode=harness.mode,
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


def _codex_config(config: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown_fields(config, CODEX_CONFIG_FIELDS, "harness.config")
    return {
        "model": _codex_model(config.get("model")),
        "version": _codex_version(config.get("version", CODEX_DEFAULT_VERSION)),
        "task_file": _workspace_path(config.get("task_file", CODEX_DEFAULT_TASK_FILE), "harness.config.task_file"),
        "timeout_seconds": _optional_positive_number(
            config.get("timeout_seconds", CODEX_DEFAULT_TIMEOUT_SECONDS),
            "harness.config.timeout_seconds",
        ),
    }


def _container_image_for_task(task: SecureBenchTask) -> str:
    environment = _task_environment(task)
    image = environment.get("image") if isinstance(environment, dict) else None
    if not isinstance(image, str) or not image.strip():
        raise ConfigError(
            "container harness mode requires benchmark environment.image; "
            "set defaults.environment.image in the manifest or environment.image on the benchmark row"
        )
    return image.strip()


def _task_environment(task: SecureBenchTask) -> dict[str, Any]:
    metadata = task.metadata if isinstance(task.metadata, dict) else {}
    environment = metadata.get("environment")
    return environment if isinstance(environment, dict) else {}


def _codex_env_names(env_names: tuple[str, ...]) -> tuple[str, ...]:
    names = tuple(env_names)
    if "CODEX_API_KEY" not in names:
        names = (*names, "CODEX_API_KEY")
    return names


def _require_env_names(env_names: tuple[str, ...], harness: str) -> None:
    missing = [name for name in env_names if not os.environ.get(name)]
    if missing:
        raise ConfigError(f"{harness} harness requires environment variable(s): {', '.join(missing)}")


def _codex_version(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("harness.config.version must be a non-empty string")
    version = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", version):
        raise ConfigError("harness.config.version contains unsupported characters")
    return version


def _codex_model(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("harness.config.model must be a non-empty string")
    model = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._+-]+", model):
        raise ConfigError("harness.config.model contains unsupported characters")
    return model


def _codex_overlay_for_image(image: str, version: str) -> CodexOverlay:
    platform = _docker_image_platform(image)
    overlay_path = _codex_overlay_cache_root() / "codex" / version / platform.cache_key
    codex_binary = overlay_path / "bin" / "codex"
    if not codex_binary.exists():
        _populate_codex_overlay_cache(overlay_path, version, platform)
    if not codex_binary.exists():
        raise ConfigError(f"Codex overlay cache did not produce expected binary: {codex_binary}")
    return CodexOverlay(path=overlay_path, platform=platform, version=version)


def _codex_overlay_cache_root() -> Path:
    return Path(os.environ.get("SECUREBENCH_AGENT_CACHE", Path.home() / ".cache" / "securebench" / "agents"))


def _docker_image_platform(image: str) -> DockerPlatform:
    inspect = _run_docker(["docker", "image", "inspect", image])
    if inspect.returncode != 0:
        pull = _run_docker(["docker", "pull", image])
        if pull.returncode != 0:
            raise ConfigError(f"Failed to pull benchmark environment image {image!r}: {pull.stderr.strip()}")
        inspect = _run_docker(["docker", "image", "inspect", image])
    if inspect.returncode != 0:
        raise ConfigError(f"Failed to inspect benchmark environment image {image!r}: {inspect.stderr.strip()}")
    try:
        data = json.loads(inspect.stdout)
        image_data = data[0] if isinstance(data, list) and data else {}
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Failed to parse Docker inspect output for {image!r}") from exc
    os_name = _normalize_docker_os(image_data.get("Os"))
    architecture = _normalize_docker_architecture(image_data.get("Architecture"))
    variant = _normalize_docker_variant(image_data.get("Variant"))
    return DockerPlatform(os=os_name, architecture=architecture, variant=variant)


def _normalize_docker_os(value: Any) -> str:
    if value != "linux":
        raise ConfigError(f"Codex mounted harness requires a linux benchmark image, got {value!r}")
    return value


def _normalize_docker_architecture(value: Any) -> str:
    if value in {"amd64", "x86_64"}:
        return "amd64"
    if value in {"arm64", "aarch64"}:
        return "arm64"
    if value == "arm":
        return "arm"
    raise ConfigError(f"Unsupported Docker image architecture for Codex overlay: {value!r}")


def _normalize_docker_variant(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and re.fullmatch(r"v[0-9]+", value):
        return value
    raise ConfigError(f"Unsupported Docker image architecture variant for Codex overlay: {value!r}")


def _populate_codex_overlay_cache(overlay_path: Path, version: str, platform: DockerPlatform) -> None:
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    cache_root = _codex_overlay_cache_root()
    install_prefix = f"/cache/codex/{version}/{platform.cache_key}"
    result = _run_docker(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            platform.docker_platform,
            "-v",
            f"{cache_root}:/cache",
            "node:22-bookworm",
            "sh",
            "-lc",
            f"npm install -g @openai/codex@{version} --prefix {install_prefix}",
        ]
    )
    if result.returncode != 0:
        raise ConfigError(f"Failed to populate Codex overlay cache: {result.stderr.strip()}")


def _run_docker(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _codex_shell_command(inner: str) -> str:
    return (
        f"export HOME={_shell_quote(CODEX_HOME_TARGET)}; "
        f"export PATH={_shell_quote(CODEX_OVERLAY_TARGET + '/bin')}:$PATH; "
        f"{inner}"
    )


def _codex_prompt(task: SecureBenchTask, task_file: str) -> str:
    extraction = default_extraction_spec(task, allow_stdout=False)
    base = f"Read {task_file} and solve the benchmark task using only public workspace data."
    return f"{base} {extraction_instructions(extraction)}"


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


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
    return (Path(root) / _workspace_dir_name(task)).resolve()


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
