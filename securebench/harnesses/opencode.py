"""OpenCode harness implementation."""

from __future__ import annotations

import json
import os
import re
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from securebench.candidates import (
    CandidateProducer,
    CandidateProduction,
    OverlayAgentCaptureResult,
    run_filesystem_overlay_agent_capture,
)
from securebench.candidates.overlay_agent import OVERLAY_AGENT_INPUTS_TARGET
from securebench.candidates.store import CandidateStore
from securebench.candidates.extraction import (
    default_extraction_spec,
    extract_candidate,
)
from securebench.errors import ConfigError
from securebench.execution_profiles import validate_executable_task
from securebench.harnesses.claude_code import allow_external_tools_config, require_env_names
from securebench.harnesses.codex import (
    DockerPlatform,
    docker_image_platform,
    run_docker,
)
from securebench.harnesses.shared import (
    agent_prompt,
    agent_workspace_git_env,
    agent_task_json,
    close_sandbox,
    container_workspace_path,
    materialize_image_workdir,
    optional_positive_number,
    prepare_overlay_agent_inputs,
    reject_git_patch_framework_collisions,
    reject_task_file_collision,
    reject_unknown_fields,
    run_timeout_seconds,
    task_allowed_domains,
    workspace_mount_target_for_task,
    workspace_path,
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


OPENCODE_CONFIG_FIELDS = {
    "provider", "model", "version", "task_file", "timeout_seconds",
    "allowed_domains", "allow_external_tools",
}
OPENCODE_OVERLAY_TARGET = "/opt/securebench/opencode"
OPENCODE_HOME_TARGET = "/opt/securebench/opencode-home"
OPENCODE_OVERLAY_AGENT_HOME_TARGET = "/tmp/securebench-opencode-home"
OPENCODE_DEFAULT_VERSION = "1.18.30"
OPENCODE_DEFAULT_TASK_FILE = "task.json"
OPENCODE_DEFAULT_TIMEOUT_SECONDS = 900.0
OPENCODE_DEFAULT_PROVIDER = "abliteration"


@dataclass(frozen=True)
class OpenCodeProvider:
    package: str
    default_model: str
    relay: ProviderRelaySpec


OPENCODE_PROVIDERS = {
    "abliteration": OpenCodeProvider(
        package="@ai-sdk/openai-compatible",
        default_model="abliterated-model",
        relay=ProviderRelaySpec(
            provider="openai",  # Relay wire protocol, independent of provider identity.
            upstream_host="api.abliteration.ai",
            credential_env="ABLIT_KEY",
            credential_kind="bearer",
            base_url=f"http://{PROVIDER_RELAY_ALIAS}:{PROVIDER_RELAY_PORT}/v1",
            allowed_client_tool_types=("function",),
            allowed_path_prefixes=("/v1/chat/completions",),
        ),
    ),
}


@dataclass(frozen=True)
class OpenCodeOverlay:
    path: Path
    platform: DockerPlatform
    version: str


class OpenCodeHarnessProducer(CandidateProducer):
    """Run OpenCode in the benchmark environment with a mounted tooling overlay."""

    def __init__(
        self,
        *,
        provider: str = OPENCODE_DEFAULT_PROVIDER,
        model: str | None = None,
        env_names: tuple[str, ...] = (),
        version: str = OPENCODE_DEFAULT_VERSION,
        task_file: str = OPENCODE_DEFAULT_TASK_FILE,
        timeout_seconds: float | None = OPENCODE_DEFAULT_TIMEOUT_SECONDS,
        allowed_domains: tuple[str, ...] = (),
        allow_external_tools: bool = False,
        workspace_root: str | Path | None = None,
    ) -> None:
        self.provider = opencode_provider(provider)
        self.model = opencode_model(
            OPENCODE_PROVIDERS[self.provider].default_model if model is None else model
        )
        self.env_names = opencode_env_names(env_names)
        self.version = opencode_version(version)
        self.task_file = task_file
        self.timeout_seconds = timeout_seconds
        self.allowed_domains = tuple(allowed_domains)
        self.allow_external_tools = allow_external_tools
        self.workspace_root = None if workspace_root is None else Path(workspace_root)
        self.materializer = VisibilityAwareMaterializer()

    def produce(self, task: BenchmarkTask, **context: Any) -> CandidateProduction:
        validate_executable_task(task)
        image = task.environment.image
        relay_spec = OPENCODE_PROVIDERS[self.provider].relay
        require_provider_credential(relay_spec)
        require_env_names(self.env_names, "opencode")
        task_workspace = workspace_root(
            task,
            context.get("workspace_root", self.workspace_root),
        )
        if task_workspace is None:
            raise ConfigError(
                "OpenCode harness requires a persistent workspace_root for stopped-state capture"
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
            state_root = Path(tempfile.mkdtemp(prefix="securebench-opencode-home-"))
            staging = HostSandbox(root=task_workspace)
            plan = self.materializer.materialize(task, staging, "agent")
            reject_task_file_collision(
                self.task_file,
                plan,
                workspace_mount_target=workspace_mount_target_for_task(task),
            )
            staging.write_file(self.task_file, agent_task_json(task))

            overlay = opencode_overlay_for_image(image, self.version)
            workspace_mount_target = workspace_mount_target_for_task(task)
            allowed_domains = task_allowed_domains(
                task,
                effective_allowed_domains("opencode", self.allowed_domains),
            )
            with docker_provider_relay_policy(
                relay_spec,
                allowed_domains,
                allow_external_tools=self.allow_external_tools,
            ) as egress:
                if egress.provider_base_url is None:
                    raise ConfigError("opencode provider relay did not provide a base URL")
                sandbox = DockerSandbox(
                    image=image,
                    root=task_workspace,
                    env_names=self.env_names,
                    env=agent_workspace_git_env(
                        task,
                        opencode_agent_env(
                            egress.env,
                            egress.provider_base_url,
                            provider=self.provider,
                            model=self.model,
                        ),
                    ),
                    network=egress.network,
                    cap_add=("DAC_OVERRIDE",),
                    read_only=False,
                    mounts=(
                        *docker_resource_mounts(plan),
                        DockerBindMount(
                            source=overlay.path,
                            target=OPENCODE_OVERLAY_TARGET,
                            read_only=True,
                        ),
                        DockerBindMount(
                            source=state_root,
                            target=OPENCODE_HOME_TARGET,
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
                        opencode_shell_command(opencode_preflight_command(self.version)),
                        timeout=timeout,
                    )
                    if preflight.exit_code != 0:
                        raise ConfigError(
                            "opencode overlay is incompatible with benchmark environment image "
                            f"{image!r}: version preflight (expected {self.version}) failed "
                            f"with exit code {preflight.exit_code}; "
                            f"stderr: {preflight.stderr.strip()}"
                        )
                    task_file_for_agent = container_workspace_path(
                        self.task_file,
                        mount_target=workspace_mount_target,
                    )
                    agent_workdir = task.environment.workdir
                    result = sandbox.run(
                        opencode_shell_command(
                            opencode_run_command(self.provider, self.model, agent_prompt(task, task_file_for_agent))
                        ),
                        workdir=agent_workdir,
                        timeout=timeout,
                    )
                    extraction = default_extraction_spec(task)
                    candidate = extract_candidate(
                        sandbox,
                        result,
                        extraction,
                    )
                    relay_summary = relay_decision_summary(egress.relay_log_dir)
                    return CandidateProduction(
                        workspace=candidate.workspace,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        metadata={
                            "harness": "opencode",
                            "exit_code": result.exit_code,
                            "task_file": self.task_file,
                            "workspace_root": str(task_workspace),
                            "benchmark_environment_image": image,
                            "opencode_version": overlay.version,
                            "opencode_model": self.model,
                            "auth_mode": "api_key",
                            "overlay_platform": overlay.platform.docker_platform,
                            "overlay_cache_path": str(overlay.path),
                            "allowed_domains": allowed_domains,
                            "provider_relay_enabled": egress.provider_relay_enabled,
                            "provider": self.provider,
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
        """Run OpenCode with bounded tool state and capture declared roots."""
        spec = task.verification.candidate
        if not isinstance(spec, FilesystemOverlayCandidate):
            raise ConfigError("OpenCode overlay capture requires a filesystem_overlay task")
        image = task.environment.image
        relay_spec = OPENCODE_PROVIDERS[self.provider].relay
        require_provider_credential(relay_spec)
        require_env_names(self.env_names, "opencode")
        task_workspace = workspace_root(
            task,
            context.get("workspace_root", self.workspace_root),
        )
        if task_workspace is None:
            raise ConfigError(
                "OpenCode harness requires a persistent workspace_root for overlay Agent inputs"
            )
        plan = prepare_overlay_agent_inputs(
            task,
            task_workspace,
            task_file=self.task_file,
            workspace_mount_target=OVERLAY_AGENT_INPUTS_TARGET,
            materializer=self.materializer,
        )
        overlay = opencode_overlay_for_image(image, self.version)
        task_file_for_agent = container_workspace_path(
            self.task_file,
            mount_target=OVERLAY_AGENT_INPUTS_TARGET,
        )
        allowed_domains = task_allowed_domains(
            task,
            effective_allowed_domains("opencode", self.allowed_domains),
        )
        timeout = run_timeout_seconds(
            task,
            context_timeout=context.get("timeout"),
            fallback_timeout=self.timeout_seconds,
        )
        with docker_provider_relay_policy(
            relay_spec,
            allowed_domains,
            allow_external_tools=self.allow_external_tools,
        ) as egress:
            if egress.provider_base_url is None:
                raise ConfigError("opencode provider relay did not provide a base URL")
            return run_filesystem_overlay_agent_capture(
                image=image,
                command=opencode_overlay_shell_command(
                    opencode_run_command(self.provider, self.model, agent_prompt(task, task_file_for_agent))
                ),
                preflight_command=opencode_overlay_shell_command(opencode_preflight_command(self.version)),
                workdir=task.environment.workdir,
                spec=spec,
                store=store,
                baseline_digest=task.baseline_digest,
                storage_root=storage_root,
                capacity_bytes=capacity_bytes,
                trusted_inputs_root=task_workspace,
                timeout=timeout,
                env=agent_workspace_git_env(
                    task,
                    opencode_agent_env(
                        egress.env,
                        egress.provider_base_url,
                        provider=self.provider,
                        model=self.model,
                    ),
                ),
                env_names=self.env_names,
                network=egress.network,
                public_mounts=(
                    *docker_resource_mounts(plan),
                    DockerBindMount(
                        source=overlay.path,
                        target=OPENCODE_OVERLAY_TARGET,
                        read_only=True,
                    ),
                ),
            )

def opencode_config(config: dict[str, Any]) -> dict[str, Any]:
    reject_unknown_fields(config, OPENCODE_CONFIG_FIELDS, "harness.config")
    provider = opencode_provider(config.get("provider", OPENCODE_DEFAULT_PROVIDER))
    return {
        "provider": provider,
        "model": opencode_model(config.get("model", OPENCODE_PROVIDERS[provider].default_model)),
        "version": opencode_version(config.get("version", OPENCODE_DEFAULT_VERSION)),
        "task_file": workspace_path(
            config.get("task_file", OPENCODE_DEFAULT_TASK_FILE), "harness.config.task_file",
        ),
        "timeout_seconds": optional_positive_number(
            config.get("timeout_seconds", OPENCODE_DEFAULT_TIMEOUT_SECONDS),
            "harness.config.timeout_seconds",
        ),
        "allowed_domains": allowed_domains_config(config.get("allowed_domains")),
        "allow_external_tools": allow_external_tools_config(config.get("allow_external_tools")),
    }


def opencode_provider(value: Any) -> str:
    if not isinstance(value, str) or value not in OPENCODE_PROVIDERS:
        raise ConfigError(f"harness.config.provider must be one of: {', '.join(OPENCODE_PROVIDERS)}")
    return value


def opencode_model(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+:/-]*", value):
        raise ConfigError("harness.config.model must be a non-empty model ID containing only letters, digits, . _ + : / -")
    return value


def opencode_version(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", value):
        raise ConfigError("harness.config.version must be an exact OpenCode version (for example 1.18.30)")
    return value


def opencode_env_names(env_names: tuple[str, ...]) -> tuple[str, ...]:
    reserved = {
        "HOME", "PATH", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy",
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN",
        *(definition.relay.credential_env for definition in OPENCODE_PROVIDERS.values()),
    }
    return tuple(
        name for name in env_names
        if name not in reserved and not name.startswith(("OPENCODE_", "XDG_"))
    )


def opencode_agent_env(
    egress_env: dict[str, str], provider_base_url: str, *, provider: str, model: str,
) -> dict[str, str]:
    definition = OPENCODE_PROVIDERS[provider]
    selected_model = f"{provider}/{model}"
    config = {
        "model": selected_model,
        "small_model": selected_model,
        "enabled_providers": [provider],
        "provider": {
            provider: {
                "npm": definition.package,
                "env": [],
                "options": {"baseURL": provider_base_url, "apiKey": "securebench-dummy-api-key"},
                "models": {model: {"name": model, "tool_call": True}},
            },
        },
        "share": "disabled",
        "autoupdate": False,
        "snapshot": False,
        "permission": "allow",
    }
    return {
        **egress_env,
        "OPENCODE_CONFIG_CONTENT": json.dumps(config),
        "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
    }


def opencode_preflight_command(version: str) -> str:
    return f'version=$(opencode --version) && test "$version" = {shlex.quote(version)}'


def opencode_run_command(provider: str, model: str, prompt: str) -> str:
    return f"opencode run --pure --auto --format json --model {shlex.quote(provider + '/' + model)} -- {shlex.quote(prompt)}"


def opencode_shell_command(inner: str, *, home_target: str = OPENCODE_HOME_TARGET) -> str:
    paths = {
        "HOME": home_target,
        "XDG_CONFIG_HOME": home_target + "/config",
        "XDG_DATA_HOME": home_target + "/data",
        "XDG_CACHE_HOME": home_target + "/cache",
        "XDG_STATE_HOME": home_target + "/state",
    }
    return (
        "umask 077; "
        + "".join(f"export {name}={shlex.quote(path)}; " for name, path in paths.items())
        + f"mkdir -p {shlex.quote(home_target)}; "
        + f"export PATH={shlex.quote(OPENCODE_OVERLAY_TARGET + '/bin')}:$PATH; "
        + inner
    )


def opencode_overlay_shell_command(inner: str) -> str:
    return opencode_shell_command(inner, home_target=OPENCODE_OVERLAY_AGENT_HOME_TARGET)


def opencode_overlay_for_image(image: str, version: str) -> OpenCodeOverlay:
    version = opencode_version(version)
    platform = docker_image_platform(image)
    if platform.os != "linux" or platform.architecture not in {"amd64", "arm64"}:
        raise ConfigError(f"Unsupported OpenCode platform: {platform.docker_platform}")
    cache_root = Path(os.environ.get("SECUREBENCH_AGENT_CACHE", Path.home() / ".cache/securebench/agents"))
    overlay_path = cache_root / "opencode" / version / platform.cache_key
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(overlay_path.parent / f".{platform.cache_key}.lock"):
        if not (overlay_path / "bin/opencode").is_file():
            populate_opencode_overlay_cache(overlay_path, version, platform)
    if not (overlay_path / "bin/opencode").is_file():
        raise ConfigError("OpenCode overlay cache did not produce bin/opencode")
    return OpenCodeOverlay(overlay_path, platform, version)


def populate_opencode_overlay_cache(overlay_path: Path, version: str, platform: DockerPlatform) -> None:
    # Extract the standalone binary; no Node or package installation is needed in the Agent.
    package = "opencode-linux-x64-baseline" if platform.architecture == "amd64" else "opencode-linux-arm64"
    with tempfile.TemporaryDirectory(prefix=".opencode-install-", dir=overlay_path.parent) as staging:
        result = run_docker([
            "docker", "run", "--rm", "--platform", platform.docker_platform,
            "--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/output",
            "-v", f"{staging}:/output", "node:22-bookworm", "sh", "-lc",
            f"cd /output && npm pack {package}@{version} --pack-destination /output "
            "&& tar -xzf *.tgz && mkdir bin && cp package/bin/opencode bin/opencode "
            "&& chmod +x bin/opencode "
            + f'&& version=$(bin/opencode --version) && test "$version" = {shlex.quote(version)}',
        ])
        if result.returncode != 0:
            raise ConfigError(f"Failed to populate OpenCode overlay cache: {result.stderr.strip()}")
        binary_dir = Path(staging) / "bin"
        if not (binary_dir / "opencode").is_file():
            raise ConfigError("OpenCode package did not contain bin/opencode")
        (overlay_path / "bin").mkdir(parents=True, exist_ok=True)
        (binary_dir / "opencode").replace(overlay_path / "bin/opencode")
