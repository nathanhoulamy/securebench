"""Executable run config loading."""

from __future__ import annotations

import hashlib
import re
import subprocess
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
DEFAULT_ENVIRONMENT_PYTHON = "3.11"
PYTHON_VERSION_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}(?:-[A-Za-z0-9._-]+)?$")
PACKAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]*$")


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
class EnvironmentRoleSection:
    setup: tuple[str, ...] = ()
    network: str | None = None
    writable: bool | None = None


@dataclass(frozen=True)
class EnvironmentSection:
    python: str = DEFAULT_ENVIRONMENT_PYTHON
    packages: tuple[str, ...] = ()
    network: str = "none"
    writable: bool = False
    setup: tuple[str, ...] = ()
    producer: EnvironmentRoleSection = field(default_factory=EnvironmentRoleSection)
    runner: EnvironmentRoleSection = field(default_factory=EnvironmentRoleSection)

    @property
    def image(self) -> str:
        return _environment_image_tag(self.python, self.packages)

    def producer_setup_commands(self) -> tuple[str, ...]:
        return (*self.setup, *self.producer.setup)

    def runner_setup_commands(self) -> tuple[str, ...]:
        return (*self.setup, *self.runner.setup)

    def producer_sandbox_policy(self) -> SandboxPolicySection:
        return _environment_sandbox_policy(self, self.producer)

    def runner_sandbox_policy(self) -> SandboxPolicySection:
        return _environment_sandbox_policy(self, self.runner)


@dataclass(frozen=True)
class RunConfig:
    schema_version: str
    run: RunSection
    dataset: DatasetSection
    adapter: AdapterSection
    producer: ProducerSection
    runner: RunnerSection
    environment: EnvironmentSection = field(default_factory=EnvironmentSection)

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
            image = self.environment.image
            _ensure_environment_image(
                image=image,
                python_version=self.environment.python,
                packages=self.environment.packages,
            )
            return WorkspaceAgentPatchProducer(
                sandbox_factory=lambda: DockerSandbox(
                    image=image,
                    env_names=() if replay_file is not None else (api_key_env,),
                    **self.environment.producer_sandbox_policy().docker_kwargs(),
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
                request_timeout=_optional_float(
                    producer_config.get("request_timeout", producer_config.get("timeout", 60.0))
                ),
                temperature=_optional_float(producer_config.get("temperature", 0.0)),
                allow_commands=_optional_str_tuple(producer_config.get("allow_commands"), "producer.config.allow_commands"),
                deny_commands=_optional_str_tuple(producer_config.get("deny_commands"), "producer.config.deny_commands"),
                setup_commands=self.environment.producer_setup_commands(),
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
            image = self.environment.image
            _ensure_environment_image(
                image=image,
                python_version=self.environment.python,
                packages=self.environment.packages,
            )
            return GitHubPatchRunner(
                image=image,
                repo_dir=str(runner_config.get("repo_dir", "repo")),
                sandbox_kwargs=self.environment.runner_sandbox_policy().docker_kwargs(),
                setup_commands=self.environment.runner_setup_commands(),
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
    _reject_removed_root_fields(data, ("sandbox",))
    environment = _environment_section(data.get("environment"))

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
    _reject_legacy_environment_fields(producer.config, "producer.config", ("image", "setup_commands"))
    runner_config = runner_data.get("config", {})
    if not isinstance(runner_config, dict):
        raise ConfigError("runner.config must be an object")
    _reject_legacy_environment_fields(runner_config, "runner.config", ("image", "setup_commands"))
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
        environment=environment,
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


def _environment_section(value: Any) -> EnvironmentSection:
    if value is None:
        return EnvironmentSection()
    if not isinstance(value, dict):
        raise ConfigError("environment must be an object")
    python_version = _environment_python(value.get("python", DEFAULT_ENVIRONMENT_PYTHON), "environment.python")
    network = _sandbox_network(value.get("network", "none"), "environment.network")
    writable = _optional_bool(value.get("writable", False), "environment.writable")
    setup = _optional_str_tuple(value.get("setup"), "environment.setup")
    return EnvironmentSection(
        python=python_version,
        packages=_environment_packages(value.get("packages"), "environment.packages"),
        network=network,
        writable=writable,
        setup=setup,
        producer=_environment_role(value.get("producer"), "environment.producer"),
        runner=_environment_role(value.get("runner"), "environment.runner"),
    )


def _environment_role(value: Any, field: str) -> EnvironmentRoleSection:
    if value is None:
        return EnvironmentRoleSection()
    if not isinstance(value, dict):
        raise ConfigError(f"{field} must be an object")
    network = None
    if "network" in value:
        network = _sandbox_network(value.get("network"), f"{field}.network")
    writable = None
    if "writable" in value:
        writable = _optional_bool(value.get("writable"), f"{field}.writable")
    return EnvironmentRoleSection(
        setup=_optional_str_tuple(value.get("setup"), f"{field}.setup"),
        network=network,
        writable=writable,
    )


def _environment_python(value: Any, field: str) -> str:
    if not isinstance(value, str) or not PYTHON_VERSION_PATTERN.fullmatch(value):
        raise ConfigError(f"{field} must be a Python version like '3.11' or '3.11-bookworm'")
    return value


def _environment_packages(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"{field} must be a list of package names")
    packages = []
    for item in value:
        if not isinstance(item, str) or not PACKAGE_NAME_PATTERN.fullmatch(item):
            raise ConfigError(f"{field} entries must be non-empty package names")
        packages.append(item)
    return tuple(sorted(dict.fromkeys(packages)))


def _environment_sandbox_policy(
    environment: EnvironmentSection,
    role: EnvironmentRoleSection,
) -> SandboxPolicySection:
    writable = environment.writable if role.writable is None else role.writable
    return SandboxPolicySection(
        network=environment.network if role.network is None else role.network,
        read_only=not writable,
    )


def _environment_image_tag(python_version: str, packages: tuple[str, ...]) -> str:
    if not packages:
        return f"securebench-agent:py{python_version}"
    digest = hashlib.sha256(
        "\n".join((python_version, *sorted(packages))).encode("utf-8")
    ).hexdigest()[:12]
    return f"securebench-agent:py{python_version}-{digest}"


def _reject_legacy_environment_fields(config: dict[str, Any], field: str, names: tuple[str, ...]) -> None:
    for name in names:
        if name in config:
            raise ConfigError(f"{field}.{name} has moved to top-level environment")


def _reject_removed_root_fields(data: dict[str, Any], names: tuple[str, ...]) -> None:
    for name in names:
        if name in data:
            raise ConfigError(f"{name} is no longer supported; use top-level environment")


def _ensure_environment_image(*, image: str, python_version: str, packages: tuple[str, ...]) -> None:
    try:
        inspect = subprocess.run(
            ["docker", "image", "inspect", image],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ConfigError(f"Failed to inspect environment image {image!r}: {exc}") from exc
    if inspect.returncode == 0:
        return

    root = Path(__file__).resolve().parents[1]
    dockerfile = root / "docker" / "agent.Dockerfile"
    try:
        build = subprocess.run(
            [
                "docker",
                "build",
                "-f",
                str(dockerfile),
                "--build-arg",
                f"PYTHON_VERSION={python_version}",
                "--build-arg",
                f"ENVIRONMENT_PACKAGES={' '.join(packages)}",
                "-t",
                image,
                str(root),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ConfigError(f"Failed to build environment image {image!r}: {exc}") from exc
    if build.returncode != 0:
        details = build.stderr.strip() or build.stdout.strip() or f"exit code {build.returncode}"
        raise ConfigError(f"Failed to build environment image {image!r}: {details}")


def _sandbox_network(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{field} must be a string")
    return _expect_literal(value, SUPPORTED_DOCKER_NETWORKS, field)


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
