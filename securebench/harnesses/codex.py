"""Codex harness implementation."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from securebench.candidates.extraction import (
    default_extraction_spec,
    extract_candidate,
    extraction_instructions,
)
from securebench.candidates import (
    CandidateProducer,
    CandidateProduction,
    OverlayAgentCaptureResult,
    run_filesystem_overlay_agent_capture,
)
from securebench.candidates.overlay_agent import OVERLAY_AGENT_INPUTS_TARGET
from securebench.candidates.store import CandidateStore
from securebench.errors import ConfigError
from securebench.execution_profiles import validate_executable_task
from securebench.harnesses.shared import (
    agent_workspace_git_env,
    agent_task_json,
    close_sandbox,
    container_workspace_path,
    container_image_for_task,
    optional_positive_number,
    prepare_overlay_agent_inputs,
    materialize_image_workdir,
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
    PROVIDER_RELAY_ALIAS,
    PROVIDER_RELAY_PORT,
    ProviderRelaySpec,
    allowed_domains_config,
    docker_provider_relay_policy,
    effective_allowed_domains,
    relay_decision_summary,
    require_provider_credential,
)
from securebench.harnesses.codex_oauth import (
    CodexOAuthError,
    codex_auth_file,
    ensure_valid_codex_oauth_credentials,
)
from securebench.locking import exclusive_file_lock
from securebench.sandboxes import DockerSandbox, HostSandbox
from securebench.sandboxes.docker import DockerBindMount
from securebench.schemas.benchmark import FilesystemOverlayCandidate
from securebench.tasks import BenchmarkTask
from securebench.workspaces.cleanup import (
    remove_untrusted_tree,
    restore_untrusted_tree_permissions,
)
from securebench.workspaces.materialization import (
    VisibilityAwareMaterializer,
    docker_resource_mounts,
)


CODEX_CONFIG_FIELDS = {
    "auth",
    "model",
    "reasoning_effort",
    "version",
    "task_file",
    "timeout_seconds",
    "allowed_domains",
    "allow_external_tools",
}
CODEX_OVERLAY_TARGET = "/opt/securebench/codex"
CODEX_HOME_TARGET = "/opt/securebench/codex-home"
CODEX_OVERLAY_AGENT_HOME_TARGET = "/tmp/securebench-codex-home"
CODEX_OVERLAY_AUTH_SEED = "securebench/tool-state/codex-auth.json"
CODEX_DEFAULT_VERSION = "latest"
CODEX_DEFAULT_TASK_FILE = "task.json"
CODEX_DEFAULT_TIMEOUT_SECONDS = 900.0
CODEX_RUNTIME_NODE_IMAGE = "node:22-bookworm"
CODEX_PROVIDER = "openai"
CODEX_PROVIDER_UPSTREAM_HOST = "api.openai.com"
CODEX_SUBSCRIPTION_UPSTREAM_HOST = "chatgpt.com"
CODEX_PROVIDER_ENV_NAMES = {"OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"}
CODEX_AUTH_MODES = {"api_key", "subscription"}
CODEX_DEFAULT_AUTH_MODE = "api_key"
CODEX_REASONING_EFFORTS = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
}
CODEX_DUMMY_API_KEY = "securebench-dummy-openai-api-key"
CODEX_DUMMY_ACCOUNT_ID = "securebench-dummy-account"
CODEX_DUMMY_USER_ID = "securebench-dummy-user"
CODEX_DUMMY_TOKEN_LIFETIME_SECONDS = 10 * 365 * 24 * 60 * 60
CODEX_RELAY_PROVIDER_ID = "securebench_openai"
CODEX_SUBSCRIPTION_RELAY_PROVIDER_ID = "securebench_chatgpt"
CODEX_PROVIDER_RELAY_SPEC = ProviderRelaySpec(
    provider=CODEX_PROVIDER,
    upstream_host=CODEX_PROVIDER_UPSTREAM_HOST,
    credential_env="OPENAI_API_KEY",
    credential_kind="bearer",
    base_url=f"http://{PROVIDER_RELAY_ALIAS}:{PROVIDER_RELAY_PORT}/v1",
    allowed_client_tool_types=("function", "custom", "shell", "apply_patch"),
    allowed_path_prefixes=("/v1/responses",),
)
CODEX_SUBSCRIPTION_RELAY_SPEC = ProviderRelaySpec(
    provider=CODEX_PROVIDER,
    upstream_host=CODEX_SUBSCRIPTION_UPSTREAM_HOST,
    credential_env=None,
    credential_kind="codex-oauth",
    base_url=f"http://{PROVIDER_RELAY_ALIAS}:{PROVIDER_RELAY_PORT}/backend-api",
    allowed_client_tool_types=CODEX_PROVIDER_RELAY_SPEC.allowed_client_tool_types,
    allowed_path_prefixes=("/backend-api/codex/",),
    allowed_methods=("GET", "POST"),
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
        auth: str = CODEX_DEFAULT_AUTH_MODE,
        model: str,
        reasoning_effort: str | None = None,
        env_names: tuple[str, ...] = (),
        version: str = CODEX_DEFAULT_VERSION,
        task_file: str = CODEX_DEFAULT_TASK_FILE,
        timeout_seconds: float | None = CODEX_DEFAULT_TIMEOUT_SECONDS,
        allowed_domains: tuple[str, ...] = (),
        allow_external_tools: bool = False,
        workspace_root: str | Path | None = None,
    ) -> None:
        self.auth = codex_auth_mode(auth)
        self.model = model
        self.reasoning_effort = codex_reasoning_effort(reasoning_effort)
        self.env_names = codex_env_names(env_names)
        self.version = codex_version(version)
        self.task_file = task_file
        self.timeout_seconds = timeout_seconds
        self.allowed_domains = tuple(allowed_domains)
        self.allow_external_tools = allow_external_tools
        self.workspace_root = None if workspace_root is None else Path(workspace_root)
        self.materializer = VisibilityAwareMaterializer()

    def produce(self, task: BenchmarkTask, **context: Any) -> CandidateProduction:
        validate_executable_task(task)
        image = container_image_for_task(task)
        relay_spec = codex_provider_relay_spec(self.auth)
        credential_file = codex_subscription_credential_file(self.auth)
        require_provider_credential(relay_spec, credential_file)
        if credential_file is not None:
            try:
                ensure_valid_codex_oauth_credentials(credential_file)
            except CodexOAuthError as exc:
                raise ConfigError(str(exc)) from exc
        require_env_names(self.env_names, "codex")
        task_workspace = workspace_root(
            task,
            context.get("workspace_root", self.workspace_root),
        )
        if task_workspace is None:
            raise ConfigError(
                "Codex harness requires a persistent workspace_root for stopped-state capture"
            )
        state_root: Path | None = None

        try:
            task_workspace.mkdir(parents=True, exist_ok=True)
            materialize_image_workdir(task, task_workspace)
            reject_git_patch_framework_collisions(
                task,
                task_workspace,
                task_file=self.task_file,
            )
            state_root = Path(tempfile.mkdtemp(prefix="securebench-codex-home-"))
            if self.auth == "subscription":
                write_dummy_codex_auth(state_root / "auth.json")
            staging = HostSandbox(root=task_workspace)
            plan = self.materializer.materialize(task, staging, "agent")
            reject_task_file_collision(
                self.task_file,
                plan,
                workspace_mount_target=workspace_mount_target_for_task(task),
            )
            staging.write_file(self.task_file, agent_task_json(task))

            overlay = codex_overlay_for_image(image, self.version)
            workspace_mount_target = workspace_mount_target_for_task(task)
            allowed_domains = task_allowed_domains(
                task,
                effective_allowed_domains("codex", self.allowed_domains),
            )
            relay_options: dict[str, Any] = {
                "allow_external_tools": self.allow_external_tools,
            }
            if credential_file is not None:
                relay_options["credential_file"] = credential_file
            with docker_provider_relay_policy(
                relay_spec,
                allowed_domains,
                **relay_options,
            ) as egress:
                if egress.provider_base_url is None:
                    raise ConfigError("codex provider relay did not provide a base URL")
                sandbox = DockerSandbox(
                    image=image,
                    root=task_workspace,
                    env_names=self.env_names,
                    env=agent_workspace_git_env(
                        task,
                        codex_agent_env(egress.env, auth=self.auth),
                    ),
                    network=egress.network,
                    cap_add=("DAC_OVERRIDE",),
                    read_only=False,
                    mounts=(
                        *docker_resource_mounts(plan),
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
                    config_args = codex_config_args(
                        egress.provider_base_url,
                        auth=self.auth,
                        reasoning_effort=self.reasoning_effort,
                        allow_external_tools=self.allow_external_tools,
                    )
                    result = sandbox.run(
                        codex_shell_command(
                            f"codex {config_args} "
                            f"exec --model {shell_quote(self.model)} --json --skip-git-repo-check "
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
                    relay_summary = relay_decision_summary(egress.relay_log_dir)
                    return CandidateProduction(
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
                            "codex_reasoning_effort": self.reasoning_effort,
                            "auth_mode": self.auth,
                            "overlay_platform": overlay.platform.docker_platform,
                            "overlay_cache_path": str(overlay.path),
                            "allowed_domains": allowed_domains,
                            "provider_relay_enabled": egress.provider_relay_enabled,
                            "provider": egress.provider,
                            "allow_external_tools": self.allow_external_tools,
                            **relay_summary,
                            **candidate.metadata,
                        },
                    )
                finally:
                    close_sandbox(sandbox)
                    restore_untrusted_tree_permissions(task_workspace, image=image)
        finally:
            if state_root is not None:
                remove_untrusted_tree(state_root, image=image)

    def capture_filesystem_overlay(
        self,
        task: BenchmarkTask,
        *,
        store: CandidateStore,
        storage_root: Path,
        capacity_bytes: int,
        **context: Any,
    ) -> OverlayAgentCaptureResult:
        """Run Codex with tool state on bounded tmpfs and capture declared roots."""
        spec = task.verification.candidate
        if not isinstance(spec, FilesystemOverlayCandidate):
            raise ConfigError("Codex overlay capture requires a filesystem_overlay task")
        image = container_image_for_task(task)
        relay_spec = codex_provider_relay_spec(self.auth)
        credential_file = codex_subscription_credential_file(self.auth)
        require_provider_credential(relay_spec, credential_file)
        if credential_file is not None:
            try:
                ensure_valid_codex_oauth_credentials(credential_file)
            except CodexOAuthError as exc:
                raise ConfigError(str(exc)) from exc
        require_env_names(self.env_names, "codex")
        task_workspace = workspace_root(
            task,
            context.get("workspace_root", self.workspace_root),
        )
        if task_workspace is None:
            raise ConfigError(
                "Codex harness requires a persistent workspace_root for overlay Agent inputs"
            )
        plan = prepare_overlay_agent_inputs(
            task,
            task_workspace,
            task_file=self.task_file,
            workspace_mount_target=OVERLAY_AGENT_INPUTS_TARGET,
            materializer=self.materializer,
        )
        auth_seed: str | None = None
        if self.auth == "subscription":
            write_dummy_codex_auth(task_workspace / CODEX_OVERLAY_AUTH_SEED)
            auth_seed = container_workspace_path(
                CODEX_OVERLAY_AUTH_SEED,
                mount_target=OVERLAY_AGENT_INPUTS_TARGET,
            )
        overlay = codex_overlay_for_image(image, self.version)
        task_file_for_agent = container_workspace_path(
            self.task_file,
            mount_target=OVERLAY_AGENT_INPUTS_TARGET,
        )
        allowed_domains = task_allowed_domains(
            task,
            effective_allowed_domains("codex", self.allowed_domains),
        )
        timeout = run_timeout_seconds(
            task,
            context_timeout=context.get("timeout"),
            fallback_timeout=self.timeout_seconds,
        )
        relay_options: dict[str, Any] = {
            "allow_external_tools": self.allow_external_tools,
        }
        if credential_file is not None:
            relay_options["credential_file"] = credential_file
        with docker_provider_relay_policy(
            relay_spec,
            allowed_domains,
            **relay_options,
        ) as egress:
            if egress.provider_base_url is None:
                raise ConfigError("codex provider relay did not provide a base URL")
            config_args = codex_config_args(
                egress.provider_base_url,
                auth=self.auth,
                reasoning_effort=self.reasoning_effort,
                allow_external_tools=self.allow_external_tools,
            )
            return run_filesystem_overlay_agent_capture(
                image=image,
                command=codex_overlay_shell_command(
                    f"codex {config_args} "
                    f"exec --model {shell_quote(self.model)} --json --skip-git-repo-check "
                    "--dangerously-bypass-approvals-and-sandbox "
                    f"{shell_quote(codex_prompt(task, task_file_for_agent))}",
                    auth_seed=auth_seed,
                ),
                preflight_command=codex_overlay_shell_command(
                    "codex --version",
                    auth_seed=auth_seed,
                ),
                workdir=codex_agent_workdir(task),
                spec=spec,
                store=store,
                baseline_digest=task.baseline_digest,
                storage_root=storage_root,
                capacity_bytes=capacity_bytes,
                trusted_inputs_root=task_workspace,
                timeout=timeout,
                env=agent_workspace_git_env(
                    task,
                    codex_agent_env(egress.env, auth=self.auth),
                ),
                env_names=self.env_names,
                network=egress.network,
                public_mounts=(
                    *docker_resource_mounts(plan),
                    DockerBindMount(
                        source=overlay.path,
                        target=CODEX_OVERLAY_TARGET,
                        read_only=True,
                    ),
                ),
            )


def codex_config(config: dict[str, Any]) -> dict[str, Any]:
    reject_unknown_fields(config, CODEX_CONFIG_FIELDS, "harness.config")
    return {
        "auth": codex_auth_mode(config.get("auth", CODEX_DEFAULT_AUTH_MODE)),
        "model": codex_model(config.get("model")),
        "reasoning_effort": codex_reasoning_effort(config.get("reasoning_effort")),
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
        "allow_external_tools": allow_external_tools_config(config.get("allow_external_tools")),
    }


def codex_env_names(env_names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in env_names if name not in CODEX_PROVIDER_ENV_NAMES)


def codex_auth_mode(value: Any) -> str:
    if not isinstance(value, str) or value not in CODEX_AUTH_MODES:
        valid = ", ".join(sorted(CODEX_AUTH_MODES))
        raise ConfigError(f"harness.config.auth must be one of: {valid}")
    return value


def codex_provider_relay_spec(auth: str) -> ProviderRelaySpec:
    if codex_auth_mode(auth) == "subscription":
        return CODEX_SUBSCRIPTION_RELAY_SPEC
    return CODEX_PROVIDER_RELAY_SPEC


def codex_subscription_credential_file(auth: str) -> Path | None:
    if codex_auth_mode(auth) == "subscription":
        return codex_auth_file()
    return None


def codex_agent_env(base: dict[str, str], *, auth: str) -> dict[str, str]:
    env = dict(base)
    if codex_auth_mode(auth) == "api_key":
        env["OPENAI_API_KEY"] = CODEX_DUMMY_API_KEY
        env["CODEX_API_KEY"] = CODEX_DUMMY_API_KEY
    return env


def allow_external_tools_config(value: Any) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ConfigError("harness.config.allow_external_tools must be a boolean")
    return value


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


def codex_reasoning_effort(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in CODEX_REASONING_EFFORTS:
        valid = ", ".join(sorted(CODEX_REASONING_EFFORTS))
        raise ConfigError(f"harness.config.reasoning_effort must be one of: {valid}")
    return value


def codex_overlay_for_image(image: str, version: str) -> CodexOverlay:
    platform = docker_image_platform(image)
    overlay_path = codex_overlay_cache_root() / "codex" / version / platform.cache_key
    codex_binary = overlay_path / "bin" / "codex"
    node_binary = overlay_path / "bin" / "node"
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = overlay_path.parent / f".{platform.cache_key}.lock"
    with exclusive_file_lock(lock_path):
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


def codex_relay_config_args(
    base_url: str,
    *,
    allow_external_tools: bool = False,
) -> str:
    args = [
        "-c",
        f"model_provider={toml_string(CODEX_RELAY_PROVIDER_ID)}",
        "-c",
        f"model_providers.{CODEX_RELAY_PROVIDER_ID}.name={toml_string('SecureBench OpenAI Relay')}",
        "-c",
        f"model_providers.{CODEX_RELAY_PROVIDER_ID}.base_url={toml_string(base_url)}",
        "-c",
        f"model_providers.{CODEX_RELAY_PROVIDER_ID}.env_key={toml_string('OPENAI_API_KEY')}",
        "-c",
        f"model_providers.{CODEX_RELAY_PROVIDER_ID}.wire_api={toml_string('responses')}",
    ]
    if not allow_external_tools:
        args.extend(
            [
                "-c",
                'web_search="disabled"',
                "-c",
                "tools.web_search=false",
            ]
        )
    return " ".join(shell_quote(arg) for arg in args)


def codex_config_args(
    base_url: str,
    *,
    auth: str,
    reasoning_effort: str | None = None,
    allow_external_tools: bool = False,
) -> str:
    if codex_auth_mode(auth) == "subscription":
        args = codex_subscription_config_args(
            base_url,
            allow_external_tools=allow_external_tools,
        )
    else:
        args = codex_relay_config_args(
            base_url,
            allow_external_tools=allow_external_tools,
        )
    effort = codex_reasoning_effort(reasoning_effort)
    if effort is not None:
        effort_override = f"model_reasoning_effort={toml_string(effort)}"
        args = f"{args} {shell_quote('-c')} {shell_quote(effort_override)}"
    return args


def codex_subscription_config_args(
    base_url: str,
    *,
    allow_external_tools: bool = False,
) -> str:
    model_base_url = codex_subscription_model_base_url(base_url)
    args = [
        "-c",
        f"model_provider={toml_string(CODEX_SUBSCRIPTION_RELAY_PROVIDER_ID)}",
        "-c",
        f"chatgpt_base_url={toml_string(base_url)}",
        "-c",
        (
            f"model_providers.{CODEX_SUBSCRIPTION_RELAY_PROVIDER_ID}."
            f"name={toml_string('SecureBench ChatGPT Relay')}"
        ),
        "-c",
        (
            f"model_providers.{CODEX_SUBSCRIPTION_RELAY_PROVIDER_ID}."
            f"base_url={toml_string(model_base_url)}"
        ),
        "-c",
        f"model_providers.{CODEX_SUBSCRIPTION_RELAY_PROVIDER_ID}.wire_api={toml_string('responses')}",
        "-c",
        f"model_providers.{CODEX_SUBSCRIPTION_RELAY_PROVIDER_ID}.requires_openai_auth=true",
        "-c",
        f"model_providers.{CODEX_SUBSCRIPTION_RELAY_PROVIDER_ID}.supports_websockets=false",
        "-c",
        'forced_login_method="chatgpt"',
        "-c",
        'cli_auth_credentials_store="file"',
    ]
    if not allow_external_tools:
        args.extend(
            [
                "-c",
                'web_search="disabled"',
                "-c",
                "tools.web_search=false",
                "-c",
                "features.image_generation=false",
            ]
        )
    return " ".join(shell_quote(arg) for arg in args)


def codex_subscription_model_base_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/codex"


def write_dummy_codex_auth(path: Path) -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    expires_at = now + CODEX_DUMMY_TOKEN_LIFETIME_SECONDS
    auth_claim = {
        "chatgpt_account_id": CODEX_DUMMY_ACCOUNT_ID,
        "chatgpt_plan_type": "pro",
        "chatgpt_user_id": CODEX_DUMMY_USER_ID,
    }
    id_token = dummy_jwt(
        {
            "exp": expires_at,
            "iat": now,
            "sub": CODEX_DUMMY_USER_ID,
            "email": "securebench@example.invalid",
            "https://api.openai.com/auth": auth_claim,
        }
    )
    access_token = dummy_jwt(
        {
            "exp": expires_at,
            "iat": now,
            "sub": CODEX_DUMMY_USER_ID,
            "https://api.openai.com/auth": auth_claim,
            "https://api.openai.com/auth.chatgpt_account_id": CODEX_DUMMY_ACCOUNT_ID,
        }
    )
    document = {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": id_token,
            "access_token": access_token,
            "refresh_token": "securebench-dummy-refresh-token",
            "account_id": CODEX_DUMMY_ACCOUNT_ID,
        },
        "last_refresh": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, sort_keys=True) + "\n")
    os.chmod(path, 0o600)


def dummy_jwt(claims: dict[str, Any]) -> str:
    header = {"alg": "none", "typ": "JWT"}
    return ".".join(
        [
            base64.urlsafe_b64encode(json.dumps(header, separators=(",", ":")).encode())
            .decode()
            .rstrip("="),
            base64.urlsafe_b64encode(json.dumps(claims, separators=(",", ":")).encode())
            .decode()
            .rstrip("="),
            "securebench",
        ]
    )


def codex_shell_command(inner: str, *, home_target: str = CODEX_HOME_TARGET) -> str:
    return (
        f"export HOME={shell_quote(home_target)}; "
        f"export CODEX_HOME={shell_quote(home_target)}; "
        f"export PATH={shell_quote(CODEX_OVERLAY_TARGET + '/bin')}:$PATH; "
        'if [ -z "$OPENAI_API_KEY" ] && [ -n "$CODEX_API_KEY" ]; then export OPENAI_API_KEY="$CODEX_API_KEY"; fi; '
        'if [ -z "$CODEX_API_KEY" ] && [ -n "$OPENAI_API_KEY" ]; then export CODEX_API_KEY="$OPENAI_API_KEY"; fi; '
        f"{inner}"
    )


def codex_overlay_shell_command(inner: str, *, auth_seed: str | None) -> str:
    """Initialize bounded, case-local Codex state before invoking the CLI."""
    home = shell_quote(CODEX_OVERLAY_AGENT_HOME_TARGET)
    setup = f"umask 077; mkdir -p {home}; "
    if auth_seed is not None:
        setup += (
            f"if [ ! -f {home}/auth.json ]; then "
            f"cp {shell_quote(auth_seed)} {home}/auth.json; fi; "
        )
    return setup + codex_shell_command(
        inner,
        home_target=CODEX_OVERLAY_AGENT_HOME_TARGET,
    )


def codex_agent_workdir(task: BenchmarkTask) -> str:
    """Return the container workdir where Codex should operate."""
    return task_workdir(task)


def codex_prompt(task: BenchmarkTask, task_file: str) -> str:
    extraction = default_extraction_spec(task)
    if task.family == "repo_patch":
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


def toml_string(value: str) -> str:
    return json.dumps(value)
