"""Executable run config loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from securebench.environment import (
    DEFAULT_ENVIRONMENT_PYTHON,
    EnvironmentRoleSection,
    EnvironmentSection,
    environment_packages,
    environment_python,
    sandbox_network,
)
from securebench.errors import ConfigError
from securebench.datasets import HuggingFaceDatasetRef
from securebench.runners import Runner
from securebench.runtime import (
    build_adapter as build_runtime_adapter,
    build_producer as build_runtime_producer,
    build_runner as build_runtime_runner,
    get_adapter_or_config_error,
)


SUPPORTED_SCHEMA_VERSION = "0.1"


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
        return build_runtime_producer(self)

    def build_runner(self) -> Runner:
        return build_runtime_runner(self)

    def build_adapter(self) -> Any:
        return build_runtime_adapter(self)


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
    get_adapter_or_config_error(adapter.id)

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
    python_version = environment_python(value.get("python", DEFAULT_ENVIRONMENT_PYTHON), "environment.python")
    network = sandbox_network(value.get("network", "none"), "environment.network")
    writable = _optional_bool(value.get("writable", False), "environment.writable")
    setup = _optional_str_tuple(value.get("setup"), "environment.setup")
    return EnvironmentSection(
        python=python_version,
        packages=environment_packages(value.get("packages"), "environment.packages"),
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
        network = sandbox_network(value.get("network"), f"{field}.network")
    writable = None
    if "writable" in value:
        writable = _optional_bool(value.get("writable"), f"{field}.writable")
    return EnvironmentRoleSection(
        setup=_optional_str_tuple(value.get("setup"), f"{field}.setup"),
        network=network,
        writable=writable,
    )


def _reject_legacy_environment_fields(config: dict[str, Any], field: str, names: tuple[str, ...]) -> None:
    for name in names:
        if name in config:
            raise ConfigError(f"{field}.{name} has moved to top-level environment")


def _reject_removed_root_fields(data: dict[str, Any], names: tuple[str, ...]) -> None:
    for name in names:
        if name in data:
            raise ConfigError(f"{name} is no longer supported; use top-level environment")


def _expect_literal(value: str, allowed: set[str], field: str) -> Any:
    if value not in allowed:
        expected = ", ".join(sorted(allowed))
        raise ConfigError(f"{field} must be one of: {expected}")
    return value


def _validate_adapter_runner_compatibility(config: RunConfig) -> None:
    adapter = get_adapter_or_config_error(config.adapter.id)
    if config.runner.type != adapter.task_type:
        raise ConfigError(
            f"runner.type must match adapter task_type {adapter.task_type!r} for adapter {config.adapter.id!r}"
        )
