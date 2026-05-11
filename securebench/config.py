"""Executable run config loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from securebench.candidates import (
    OpenAICompatibleChatClient,
    OpenAICompatibleChatConfig,
    StaticCandidateProducer,
    TextCompletionProducer,
    WorkspaceAgentPatchProducer,
)
from securebench.adapters import get_adapter
from securebench.datasets import HuggingFaceDatasetRef
from securebench.runners import CodeGenerationRunner, GitHubPatchRunner, MultipleChoiceRunner, Runner
from securebench.sandboxes import DockerSandbox


SUPPORTED_SCHEMA_VERSION = "0.1"
SUPPORTED_DOCKER_NETWORKS = {"none", "bridge"}


class ConfigError(ValueError):
    """Raised when a run config is invalid."""


@dataclass(frozen=True)
class RunSection:
    id: str
    output_path: Path
    limit: int | None = None


@dataclass(frozen=True)
class DatasetSection:
    provider: Literal["huggingface"]
    name: str
    split: str
    config: str | None = None
    revision: str | None = None
    streaming: bool = False


@dataclass(frozen=True)
class AdapterSection:
    id: str


@dataclass(frozen=True)
class ProducerSection:
    type: Literal["openai_compatible", "static", "workspace_agent_patch"]
    config: dict[str, Any]


@dataclass(frozen=True)
class RunnerSection:
    type: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SandboxPolicySection:
    network: str = "none"
    cap_drop: tuple[str, ...] = ("ALL",)
    read_only: bool = True
    tmpfs: tuple[str, ...] = ("/tmp",)
    mem_limit: str | None = "1g"
    pids_limit: int | None = 256
    security_opt: tuple[str, ...] = ("no-new-privileges:true",)

    def docker_kwargs(self) -> dict[str, Any]:
        return {
            "network": self.network,
            "cap_drop": self.cap_drop,
            "read_only": self.read_only,
            "tmpfs": self.tmpfs,
            "mem_limit": self.mem_limit,
            "pids_limit": self.pids_limit,
            "security_opt": self.security_opt,
        }


@dataclass(frozen=True)
class SandboxSection:
    defaults: SandboxPolicySection = field(default_factory=SandboxPolicySection)
    agent_workspace: SandboxPolicySection = field(default_factory=SandboxPolicySection)
    test_sandbox: SandboxPolicySection = field(default_factory=SandboxPolicySection)


@dataclass(frozen=True)
class RunConfig:
    schema_version: str
    run: RunSection
    dataset: DatasetSection
    adapter: AdapterSection
    producer: ProducerSection
    runner: RunnerSection
    sandbox: SandboxSection = field(default_factory=SandboxSection)

    def dataset_ref(self) -> HuggingFaceDatasetRef:
        return HuggingFaceDatasetRef(
            name=self.dataset.name,
            config=self.dataset.config,
            split=self.dataset.split,
            revision=self.dataset.revision,
            streaming=self.dataset.streaming,
        )

    def build_producer(self) -> Any:
        if self.producer.type == "static":
            return StaticCandidateProducer(_required_str(self.producer.config, "text", "producer.config"))

        if self.producer.type == "openai_compatible":
            client = OpenAICompatibleChatClient(
                OpenAICompatibleChatConfig(
                    model=_required_str(self.producer.config, "model", "producer.config"),
                    base_url=str(self.producer.config.get("base_url", "https://api.openai.com/v1")),
                    api_key_env=str(self.producer.config.get("api_key_env", "OPENAI_API_KEY")),
                    timeout=_optional_float(self.producer.config.get("timeout")),
                    temperature=_optional_float(self.producer.config.get("temperature", 0.0)),
                    system_prompt=str(
                        self.producer.config.get(
                            "system_prompt",
                            "Return only the letter of the correct choice.",
                        )
                    ),
                    extra_body=_optional_dict(self.producer.config.get("extra_body")),
                )
            )
            return TextCompletionProducer(client, name="openai-compatible")

        if self.producer.type == "workspace_agent_patch":
            producer_config = self.producer.config
            model = _optional_str(producer_config.get("model"))
            replay_file = _optional_str(producer_config.get("replay_file"))
            if model is None and replay_file is None:
                raise ConfigError("producer.config requires either model or replay_file")
            api_key_env = str(producer_config.get("api_key_env", "OPENAI_API_KEY"))
            return WorkspaceAgentPatchProducer(
                sandbox_factory=lambda: DockerSandbox(
                    image=str(producer_config.get("image", "python:3.11-slim")),
                    env_names=() if replay_file is not None else (api_key_env,),
                    **self.sandbox.agent_workspace.docker_kwargs(),
                ),
                model=model,
                replay_file=replay_file,
                repo_dir=str(producer_config.get("repo_dir", "repo")),
                task_file=str(producer_config.get("task_file", "SECUREBENCH_TASK.md")),
                base_url=str(producer_config.get("base_url", "https://api.openai.com/v1")),
                api_key_env=api_key_env,
                max_steps=_optional_positive_int(
                    producer_config.get("max_steps"),
                    default=40,
                    field="producer.config.max_steps",
                ),
                max_tool_output=_optional_positive_int(
                    producer_config.get("max_tool_output"),
                    default=12_000,
                    field="producer.config.max_tool_output",
                ),
                command_timeout=_optional_float_default(
                    producer_config.get("command_timeout"),
                    default=60.0,
                    field="producer.config.command_timeout",
                ),
                request_timeout=_optional_float(producer_config.get("request_timeout", producer_config.get("timeout", 60.0))),
                temperature=_optional_float(producer_config.get("temperature", 0.0)),
                allow_commands=_optional_str_tuple(producer_config.get("allow_commands"), "producer.config.allow_commands"),
                deny_commands=_optional_str_tuple(producer_config.get("deny_commands"), "producer.config.deny_commands"),
                setup_commands=_optional_str_tuple(producer_config.get("setup_commands"), "producer.config.setup_commands"),
                timeout=_optional_float(producer_config.get("timeout")),
            )

        raise ConfigError(f"Unsupported producer type {self.producer.type!r}")

    def build_runner(self) -> Runner:
        if self.runner.type == "multiple_choice":
            return MultipleChoiceRunner()
        if self.runner.type == "code_generation":
            return CodeGenerationRunner()
        if self.runner.type == "github_patch":
            runner_config = self.runner.config or {}
            return GitHubPatchRunner(
                image=str(runner_config.get("image", "python:3.11-slim")),
                repo_dir=str(runner_config.get("repo_dir", "repo")),
                sandbox_kwargs=self.sandbox.test_sandbox.docker_kwargs(),
                setup_commands=_optional_str_tuple(runner_config.get("setup_commands"), "runner.config.setup_commands"),
                test_commands=_optional_str_tuple(runner_config.get("test_commands"), "runner.config.test_commands"),
                apply_hidden_patches=_optional_str_tuple(
                    runner_config.get("apply_hidden_patches"),
                    "runner.config.apply_hidden_patches",
                ),
                test_group_names=_optional_str_tuple(
                    runner_config.get("test_group_names"),
                    "runner.config.test_group_names",
                ),
                test_command_template=_optional_str(runner_config.get("test_command_template")),
                timeout=_optional_float_default(
                    runner_config.get("timeout"),
                    default=120.0,
                    field="runner.config.timeout",
                ),
            )
        raise ConfigError(f"Unsupported runner type {self.runner.type!r}")

    def build_adapter(self) -> Any:
        return _get_adapter_or_config_error(self.adapter.id)


def load_run_config(path: str | Path) -> RunConfig:
    """Load a run config from a YAML file."""
    loaded = yaml.safe_load(Path(path).read_text())
    if not isinstance(loaded, dict):
        raise ConfigError("Run config root must be an object")
    return parse_run_config(loaded)


def parse_run_config(data: dict[str, Any]) -> RunConfig:
    """Parse and validate a run config object."""
    schema_version = _required_str(data, "schema_version", "root")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise ConfigError(f"Unsupported schema_version {schema_version!r}")

    run_data = _required_dict(data, "run", "root")
    dataset_data = _required_dict(data, "dataset", "root")
    adapter_data = _required_dict(data, "adapter", "root")
    producer_data = _required_dict(data, "producer", "root")
    runner_data = _required_dict(data, "runner", "root")
    sandbox = _sandbox_section(data.get("sandbox"))

    dataset = DatasetSection(
        provider=_expect_literal(_required_str(dataset_data, "provider", "dataset"), {"huggingface"}, "dataset.provider"),
        name=_required_str(dataset_data, "name", "dataset"),
        config=_optional_str(dataset_data.get("config")),
        split=_required_str(dataset_data, "split", "dataset"),
        revision=_optional_str(dataset_data.get("revision")),
        streaming=_optional_bool(dataset_data.get("streaming", False), "dataset.streaming"),
    )

    adapter = AdapterSection(id=_required_str(adapter_data, "id", "adapter"))
    _get_adapter_or_config_error(adapter.id)

    producer = ProducerSection(
        type=_expect_literal(
            _required_str(producer_data, "type", "producer"),
            {"openai_compatible", "static", "workspace_agent_patch"},
            "producer.type",
        ),
        config=_required_dict(producer_data, "config", "producer"),
    )
    runner_config = runner_data.get("config", {})
    if not isinstance(runner_config, dict):
        raise ConfigError("runner.config must be an object")
    runner = RunnerSection(
        type=_required_str(runner_data, "type", "runner"),
        config=runner_config,
    )

    limit = run_data.get("limit")
    config = RunConfig(
        schema_version=schema_version,
        run=RunSection(
            id=_required_str(run_data, "id", "run"),
            limit=None if limit is None else _positive_int(limit, "run.limit"),
            output_path=Path(_required_str(run_data, "output_path", "run")),
        ),
        dataset=dataset,
        adapter=adapter,
        producer=producer,
        runner=runner,
        sandbox=sandbox,
    )
    _validate_adapter_runner_compatibility(config)
    return config


def _required_dict(data: dict[str, Any], key: str, section: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{section}.{key} must be an object")
    return value


def _required_str(data: dict[str, Any], key: str, section: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{section}.{key} must be a non-empty string")
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigError("Optional string field must be a string when provided")
    return value


def _optional_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{field} must be a boolean")
    return value


def _positive_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{field} must be a positive integer")
    return value


def _optional_positive_int(value: Any, *, default: int, field: str) -> int:
    if value is None:
        return default
    return _positive_int(value, field)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError("Optional integer field must be an integer when provided")
    return value


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError("Optional numeric field must be a number when provided")
    return float(value)


def _optional_float_default(value: Any, *, default: float, field: str) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field} must be a number")
    return float(value)


def _optional_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("Optional object field must be an object when provided")
    return value


def _optional_str_tuple(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ConfigError(f"{field} must be a list of non-empty strings")
    return tuple(value)


def _sandbox_section(value: Any) -> SandboxSection:
    if value is None:
        return SandboxSection()
    if not isinstance(value, dict):
        raise ConfigError("sandbox must be an object")
    defaults = _sandbox_policy(value.get("defaults"), SandboxPolicySection(), "sandbox.defaults")
    return SandboxSection(
        defaults=defaults,
        agent_workspace=_sandbox_policy(value.get("agent_workspace"), defaults, "sandbox.agent_workspace"),
        test_sandbox=_sandbox_policy(value.get("test_sandbox"), defaults, "sandbox.test_sandbox"),
    )


def _sandbox_policy(value: Any, base: SandboxPolicySection, field: str) -> SandboxPolicySection:
    if value is None:
        return base
    if not isinstance(value, dict):
        raise ConfigError(f"{field} must be an object")
    return SandboxPolicySection(
        network=_sandbox_network(value.get("network", base.network), f"{field}.network"),
        cap_drop=_non_empty_str_tuple(value.get("cap_drop", list(base.cap_drop)), f"{field}.cap_drop"),
        read_only=_optional_bool(value.get("read_only", base.read_only), f"{field}.read_only"),
        tmpfs=_non_empty_str_tuple(value.get("tmpfs", list(base.tmpfs)), f"{field}.tmpfs"),
        mem_limit=_optional_mem_limit(value.get("mem_limit", base.mem_limit), f"{field}.mem_limit"),
        pids_limit=_optional_positive_int_or_none(value.get("pids_limit", base.pids_limit), f"{field}.pids_limit"),
        security_opt=_non_empty_str_tuple(
            value.get("security_opt", list(base.security_opt)),
            f"{field}.security_opt",
        ),
    )


def _sandbox_network(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{field} must be a string")
    return _expect_literal(value, SUPPORTED_DOCKER_NETWORKS, field)


def _non_empty_str_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ConfigError(f"{field} must be a list of non-empty strings")
    return tuple(value)


def _optional_mem_limit(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a non-empty string or null")
    return value


def _optional_positive_int_or_none(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field)


def _expect_literal(value: str, allowed: set[str], field: str) -> Any:
    if value not in allowed:
        expected = ", ".join(sorted(allowed))
        raise ConfigError(f"{field} must be one of: {expected}")
    return value


def _validate_adapter_runner_compatibility(config: RunConfig) -> None:
    adapter = _get_adapter_or_config_error(config.adapter.id)
    if config.runner.type != adapter.task_type:
        raise ConfigError(
            f"runner.type must match adapter task_type {adapter.task_type!r} for adapter {config.adapter.id!r}"
        )


def _get_adapter_or_config_error(adapter_id: str) -> Any:
    try:
        return get_adapter(adapter_id)
    except KeyError as exc:
        raise ConfigError(str(exc)) from exc
