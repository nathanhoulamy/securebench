"""Claude Code harness implementation."""

from __future__ import annotations

import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from securebench.candidates import CandidateProducer, CandidateProduction
from securebench.candidates.extraction import (
    default_extraction_spec,
    extract_candidate,
    extraction_instructions,
)
from securebench.errors import ConfigError
from securebench.execution_profiles import validate_executable_task
from securebench.harnesses.codex import (
    DockerPlatform,
    docker_image_platform,
    run_docker,
    shell_quote,
)
from securebench.harnesses.shared import (
    agent_task_json,
    close_sandbox,
    container_image_for_task,
    container_workspace_path,
    materialize_image_workdir,
    optional_positive_number,
    reject_task_file_collision,
    reject_unknown_fields,
    run_timeout_seconds,
    task_allowed_domains,
    task_workdir,
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
from securebench.sandboxes import DockerSandbox, HostSandbox
from securebench.sandboxes.docker import DockerBindMount
from securebench.tasks import BenchmarkTask
from securebench.workspaces.materialization import (
    VisibilityAwareMaterializer,
    docker_resource_mounts,
)


_CLAUDE_CODE_OVERLAY_CACHE_LOCK = threading.Lock()


CLAUDE_CODE_CONFIG_FIELDS = {
    "auth",
    "model",
    "version",
    "task_file",
    "timeout_seconds",
    "allowed_domains",
    "allow_external_tools",
}
CLAUDE_CODE_OVERLAY_TARGET = "/opt/securebench/claude-code"
CLAUDE_CODE_HOME_TARGET = "/opt/securebench/claude-home"
CLAUDE_CODE_DEFAULT_MODEL = "sonnet"
CLAUDE_CODE_DEFAULT_VERSION = "latest"
CLAUDE_CODE_DEFAULT_TASK_FILE = "task.json"
CLAUDE_CODE_DEFAULT_TIMEOUT_SECONDS = 900.0
CLAUDE_CODE_RUNTIME_NODE_IMAGE = "node:22-bookworm"
CLAUDE_CODE_PROVIDER = "anthropic"
CLAUDE_CODE_PROVIDER_UPSTREAM_HOST = "api.anthropic.com"
CLAUDE_CODE_PROVIDER_ENV_NAMES = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
}
CLAUDE_CODE_AUTH_MODES = {"api_key", "subscription"}
CLAUDE_CODE_DEFAULT_AUTH_MODE = "api_key"
CLAUDE_CODE_DUMMY_API_KEY = "securebench-dummy-anthropic-api-key"
CLAUDE_CODE_DUMMY_OAUTH_TOKEN = "sk-ant-oat01-securebench-dummy-oauth-token"
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"
CLAUDE_CODE_DISABLE_AUTOUPDATER = "DISABLE_AUTOUPDATER"
CLAUDE_CODE_BLOCKED_TOOL_TYPES = (
    "mcp",
    "mcp_tool",
    "mcp_connector",
    "code_execution",
    "web_search",
    "web_fetch",
    "server_tool",
)
CLAUDE_CODE_BLOCKED_TOOL_PREFIXES = (
    "web_search_",
    "web_fetch_",
    "code_execution_",
    "computer_use_",
)
CLAUDE_CODE_PROVIDER_RELAY_SPEC = ProviderRelaySpec(
    provider=CLAUDE_CODE_PROVIDER,
    upstream_host=CLAUDE_CODE_PROVIDER_UPSTREAM_HOST,
    credential_env="ANTHROPIC_API_KEY",
    credential_kind="x-api-key",
    base_url=f"http://{PROVIDER_RELAY_ALIAS}:{PROVIDER_RELAY_PORT}",
    blocked_tool_types=CLAUDE_CODE_BLOCKED_TOOL_TYPES,
    blocked_tool_prefixes=CLAUDE_CODE_BLOCKED_TOOL_PREFIXES,
)
CLAUDE_CODE_SUBSCRIPTION_RELAY_SPEC = ProviderRelaySpec(
    provider=CLAUDE_CODE_PROVIDER,
    upstream_host=CLAUDE_CODE_PROVIDER_UPSTREAM_HOST,
    credential_env="CLAUDE_CODE_OAUTH_TOKEN",
    credential_kind="bearer",
    base_url=f"http://{PROVIDER_RELAY_ALIAS}:{PROVIDER_RELAY_PORT}",
    blocked_tool_types=CLAUDE_CODE_BLOCKED_TOOL_TYPES,
    blocked_tool_prefixes=CLAUDE_CODE_BLOCKED_TOOL_PREFIXES,
)


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
        auth: str = CLAUDE_CODE_DEFAULT_AUTH_MODE,
        model: str = CLAUDE_CODE_DEFAULT_MODEL,
        env_names: tuple[str, ...] = (),
        version: str = CLAUDE_CODE_DEFAULT_VERSION,
        task_file: str = CLAUDE_CODE_DEFAULT_TASK_FILE,
        timeout_seconds: float | None = CLAUDE_CODE_DEFAULT_TIMEOUT_SECONDS,
        allowed_domains: tuple[str, ...] = (),
        allow_external_tools: bool = False,
        workspace_root: str | Path | None = None,
    ) -> None:
        self.auth = claude_code_auth_mode(auth)
        self.model = claude_code_model(model)
        self.env_names = claude_code_env_names(env_names)
        self.version = claude_code_version(version)
        self.task_file = task_file
        self.timeout_seconds = timeout_seconds
        self.allowed_domains = tuple(allowed_domains)
        self.allow_external_tools = allow_external_tools
        self.workspace_root = None if workspace_root is None else Path(workspace_root)
        self.materializer = VisibilityAwareMaterializer()

    def produce(self, task: BenchmarkTask, **context: Any) -> CandidateProduction:
        validate_executable_task(task)
        image = container_image_for_task(task)
        relay_spec = claude_code_provider_relay_spec(self.auth)
        require_provider_credential(relay_spec)
        require_env_names(self.env_names, "claude_code")
        task_workspace = workspace_root(
            task,
            context.get("workspace_root", self.workspace_root),
        )
        if task_workspace is None:
            raise ConfigError(
                "Claude Code harness requires a persistent workspace_root for stopped-state capture"
            )
        state_cleanup = None

        try:
            task_workspace.mkdir(parents=True, exist_ok=True)
            materialize_image_workdir(task, task_workspace)
            state_cleanup = tempfile.TemporaryDirectory(prefix="securebench-claude-home-")
            state_root = Path(state_cleanup.name)
            staging = HostSandbox(root=task_workspace)
            plan = self.materializer.materialize(task, staging, "agent")
            reject_task_file_collision(self.task_file, plan)
            staging.write_file(self.task_file, agent_task_json(task))

            overlay = claude_code_overlay_for_image(image, self.version)
            workspace_mount_target = workspace_mount_target_for_task(task)
            allowed_domains = task_allowed_domains(
                task,
                effective_allowed_domains("claude_code", self.allowed_domains),
            )
            with docker_provider_relay_policy(
                relay_spec,
                allowed_domains,
                allow_external_tools=self.allow_external_tools,
            ) as egress:
                if egress.provider_base_url is None:
                    raise ConfigError("claude_code provider relay did not provide a base URL")
                sandbox = DockerSandbox(
                    image=image,
                    root=task_workspace,
                    env_names=self.env_names,
                    env=claude_code_agent_env(
                        egress.env,
                        egress.provider_base_url,
                        self.env_names,
                        auth=self.auth,
                    ),
                    network=egress.network,
                    read_only=False,
                    mounts=(
                        *docker_resource_mounts(plan),
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
                    timeout = run_timeout_seconds(
                        task,
                        context_timeout=context.get("timeout"),
                        fallback_timeout=self.timeout_seconds,
                    )
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
                            "harness": "claude_code",
                            "exit_code": result.exit_code,
                            "task_file": self.task_file,
                            "workspace_root": str(task_workspace),
                            "benchmark_environment_image": image,
                            "claude_code_version": overlay.version,
                            "claude_code_model": self.model,
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
        finally:
            if state_cleanup is not None:
                state_cleanup.cleanup()


def claude_code_config(config: dict[str, Any]) -> dict[str, Any]:
    reject_unknown_fields(config, CLAUDE_CODE_CONFIG_FIELDS, "harness.config")
    return {
        "auth": claude_code_auth_mode(
            config.get("auth", CLAUDE_CODE_DEFAULT_AUTH_MODE)
        ),
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
        "allowed_domains": allowed_domains_config(config.get("allowed_domains")),
        "allow_external_tools": allow_external_tools_config(config.get("allow_external_tools")),
    }


def claude_code_env_names(env_names: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name for name in env_names if name not in CLAUDE_CODE_PROVIDER_ENV_NAMES)


def claude_code_auth_mode(value: Any) -> str:
    if not isinstance(value, str) or value not in CLAUDE_CODE_AUTH_MODES:
        choices = ", ".join(sorted(CLAUDE_CODE_AUTH_MODES))
        raise ConfigError(f"harness.config.auth must be one of: {choices}")
    return value


def claude_code_provider_relay_spec(auth: str) -> ProviderRelaySpec:
    if auth == "subscription":
        return CLAUDE_CODE_SUBSCRIPTION_RELAY_SPEC
    return CLAUDE_CODE_PROVIDER_RELAY_SPEC


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
    with _CLAUDE_CODE_OVERLAY_CACHE_LOCK:
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


def claude_code_agent_env(
    egress_env: dict[str, str],
    provider_base_url: str,
    env_names: tuple[str, ...],
    *,
    auth: str = CLAUDE_CODE_DEFAULT_AUTH_MODE,
) -> dict[str, str]:
    env = {
        **egress_env,
        "ANTHROPIC_BASE_URL": provider_base_url,
    }
    if auth == "subscription":
        env["CLAUDE_CODE_OAUTH_TOKEN"] = CLAUDE_CODE_DUMMY_OAUTH_TOKEN
    else:
        env["ANTHROPIC_API_KEY"] = CLAUDE_CODE_DUMMY_API_KEY
    if CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC not in env_names:
        env[CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC] = "1"
    if CLAUDE_CODE_DISABLE_AUTOUPDATER not in env_names:
        env[CLAUDE_CODE_DISABLE_AUTOUPDATER] = "1"
    return env


def claude_code_shell_command(inner: str) -> str:
    return (
        f"export HOME={shell_quote(CLAUDE_CODE_HOME_TARGET)}; "
        f"export PATH={shell_quote(CLAUDE_CODE_OVERLAY_TARGET + '/bin')}:$PATH; "
        f"{inner}"
    )


def claude_code_agent_workdir(task: BenchmarkTask) -> str:
    return task_workdir(task)


def claude_code_prompt(task: BenchmarkTask, task_file: str) -> str:
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
