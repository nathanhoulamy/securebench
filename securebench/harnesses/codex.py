"""Codex mounted harness implementation."""

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
    container_image_for_task,
    optional_positive_number,
    reject_task_file_collision,
    reject_unknown_fields,
    workspace_path,
    workspace_root,
)
from securebench.workspaces.materialization import VisibilityAwareMaterializer, docker_read_only_mounts
from securebench.sandboxes import DockerSandbox, HostSandbox
from securebench.sandboxes.docker import DockerBindMount
from securebench.tasks import SecureBenchTask


CODEX_CONFIG_FIELDS = {"model", "version", "task_file", "timeout_seconds"}
CODEX_OVERLAY_TARGET = "/opt/securebench/codex"
CODEX_HOME_TARGET = "/opt/securebench/codex-home"
CODEX_DEFAULT_VERSION = "latest"
CODEX_DEFAULT_TASK_FILE = "task.json"
CODEX_DEFAULT_TIMEOUT_SECONDS = 900.0


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
        self.env_names = codex_env_names(env_names)
        self.version = codex_version(version)
        self.task_file = task_file
        self.timeout_seconds = timeout_seconds
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
        task_workspace.mkdir(parents=True, exist_ok=True)
        state_cleanup = tempfile.TemporaryDirectory(prefix="securebench-codex-home-")
        state_root = Path(state_cleanup.name)

        try:
            staging = HostSandbox(root=task_workspace)
            plan = self.materializer.materialize(task, staging, "agent")
            reject_task_file_collision(self.task_file, plan)
            staging.write_file(self.task_file, agent_task_json(task))

            overlay = codex_overlay_for_image(image, self.version)
            sandbox = DockerSandbox(
                image=image,
                root=task_workspace,
                env_names=self.env_names,
                network="bridge",
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
            )
            try:
                preflight = sandbox.run(
                    codex_shell_command("codex --version"),
                    timeout=context.get("timeout", self.timeout_seconds),
                )
                if preflight.exit_code != 0:
                    raise ConfigError(
                        "codex mounted overlay is incompatible with benchmark environment image "
                        f"{image!r}: codex --version failed with exit code {preflight.exit_code}; "
                        f"stderr: {preflight.stderr.strip()}"
                    )
                result = sandbox.run(
                    codex_shell_command(
                        f"codex exec --model {shell_quote(self.model)} --json --skip-git-repo-check "
                        f"--dangerously-bypass-approvals-and-sandbox "
                        f"{shell_quote(codex_prompt(task, self.task_file))}"
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
                        "workspace_root": str(task_workspace),
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
                close_sandbox(sandbox)
        finally:
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
    }


def codex_env_names(env_names: tuple[str, ...]) -> tuple[str, ...]:
    names = tuple(env_names)
    if "CODEX_API_KEY" not in names:
        names = (*names, "CODEX_API_KEY")
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
    if not codex_binary.exists():
        populate_codex_overlay_cache(overlay_path, version, platform)
    if not codex_binary.exists():
        raise ConfigError(f"Codex overlay cache did not produce expected binary: {codex_binary}")
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
        raise ConfigError(f"Codex mounted harness requires a linux benchmark image, got {value!r}")
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
            "node:22-bookworm",
            "sh",
            "-lc",
            f"npm install -g @openai/codex@{version} --prefix {install_prefix}",
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
        f"{inner}"
    )


def codex_prompt(task: SecureBenchTask, task_file: str) -> str:
    extraction = default_extraction_spec(task, allow_stdout=False)
    base = f"Read {task_file} and solve the benchmark task using only public workspace data."
    return f"{base} {extraction_instructions(extraction)}"


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
