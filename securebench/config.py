"""Executable run config loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from securebench.candidates import (
    OpenAICompatibleChatClient,
    OpenAICompatibleChatConfig,
    StaticCandidateProducer,
    TextCompletionProducer,
)
from securebench.adapters import get_adapter
from securebench.datasets import HuggingFaceDatasetRef
from securebench.runners import CodeGenerationRunner, GitHubPatchRunner, MultipleChoiceRunner, Runner


SUPPORTED_SCHEMA_VERSION = "0.1"


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
    kind: Literal["openai_compatible", "static"]
    config: dict[str, Any]


@dataclass(frozen=True)
class RunnerSection:
    type: str


@dataclass(frozen=True)
class RunConfig:
    schema_version: str
    run: RunSection
    dataset: DatasetSection
    adapter: AdapterSection
    producer: ProducerSection
    runner: RunnerSection

    def dataset_ref(self) -> HuggingFaceDatasetRef:
        return HuggingFaceDatasetRef(
            name=self.dataset.name,
            config=self.dataset.config,
            split=self.dataset.split,
            revision=self.dataset.revision,
            streaming=self.dataset.streaming,
        )

    def build_producer(self) -> Any:
        if self.producer.kind == "static":
            return StaticCandidateProducer(_required_str(self.producer.config, "text", "producer.config"))

        if self.producer.kind == "openai_compatible":
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

        raise ConfigError(f"Unsupported producer kind {self.producer.kind!r}")

    def build_runner(self) -> Runner:
        if self.runner.type == "multiple_choice":
            return MultipleChoiceRunner()
        if self.runner.type == "code_generation":
            return CodeGenerationRunner()
        if self.runner.type == "github_patch":
            return GitHubPatchRunner()
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
        kind=_expect_literal(
            _required_str(producer_data, "kind", "producer"),
            {"openai_compatible", "static"},
            "producer.kind",
        ),
        config=_required_dict(producer_data, "config", "producer"),
    )
    runner = RunnerSection(type=_required_str(runner_data, "type", "runner"))

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


def _optional_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("Optional object field must be an object when provided")
    return value


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
