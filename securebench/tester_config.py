"""Tester-owned benchmark-pack execution config loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from securebench.errors import ConfigError


SUPPORTED_TESTER_SCHEMA_VERSION = "0.2"
HarnessType = Literal["codex", "claude_code", "command", "submission"]
HarnessMode = Literal["host", "container", "mounted", "submission"]

ROOT_FIELDS = {"schema_version", "run", "benchmark", "harness"}
RUN_FIELDS = {"id", "output_dir"}
BENCHMARK_FIELDS = {"manifest", "tasks"}
HARNESS_FIELDS = {"type", "mode", "env", "path", "config"}
HARNESS_TYPES = {"codex", "claude_code", "command", "submission"}
HARNESS_MODES = {"host", "container", "mounted", "submission"}


@dataclass(frozen=True)
class TesterRunSection:
    """One tester-owned execution identity and output location."""

    id: str
    output_dir: Path


@dataclass(frozen=True)
class TesterBenchmarkSection:
    """Benchmark pack files selected for this execution."""

    manifest: Path
    tasks: Path


@dataclass(frozen=True)
class TesterHarnessSection:
    """Candidate-producing harness selected by the tester."""

    type: HarnessType
    mode: HarnessMode
    env: tuple[str, ...] = ()
    path: Path | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TesterConfig:
    """Parsed tester YAML for a benchmark-pack run."""

    schema_version: str
    run: TesterRunSection
    benchmark: TesterBenchmarkSection
    harness: TesterHarnessSection


def load_tester_config(path: str | Path) -> TesterConfig:
    """Load a tester config from a YAML file."""
    config_path = Path(path)
    loaded = yaml.safe_load(config_path.read_text())
    if not isinstance(loaded, dict):
        raise ConfigError("Tester config root must be an object")
    return parse_tester_config(loaded, base_dir=config_path.parent)


def parse_tester_config(data: dict[str, Any], *, base_dir: str | Path | None = None) -> TesterConfig:
    """Parse and validate a tester config object."""
    if not isinstance(data, dict):
        raise ConfigError("Tester config root must be an object")
    _reject_unknown_fields(data, ROOT_FIELDS, "root")
    schema_version = _required_str(data, "schema_version", "root")
    if schema_version != SUPPORTED_TESTER_SCHEMA_VERSION:
        raise ConfigError(f"Unsupported tester schema_version {schema_version!r}")

    run_data = _required_dict(data, "run", "root")
    benchmark_data = _required_dict(data, "benchmark", "root")
    harness_data = _required_dict(data, "harness", "root")
    _reject_unknown_fields(run_data, RUN_FIELDS, "run")
    _reject_unknown_fields(benchmark_data, BENCHMARK_FIELDS, "benchmark")
    _reject_unknown_fields(harness_data, HARNESS_FIELDS, "harness")

    base = None if base_dir is None else Path(base_dir)
    run = TesterRunSection(
        id=_required_str(run_data, "id", "run"),
        output_dir=_config_path(_required_str(run_data, "output_dir", "run"), base),
    )
    benchmark = TesterBenchmarkSection(
        manifest=_config_path(_required_str(benchmark_data, "manifest", "benchmark"), base),
        tasks=_config_path(_required_str(benchmark_data, "tasks", "benchmark"), base),
    )
    harness = _harness_section(harness_data, base)
    return TesterConfig(
        schema_version=schema_version,
        run=run,
        benchmark=benchmark,
        harness=harness,
    )


def _harness_section(data: dict[str, Any], base_dir: Path | None) -> TesterHarnessSection:
    harness_type = _expect_literal(_required_str(data, "type", "harness"), HARNESS_TYPES, "harness.type")
    mode = _expect_literal(_required_str(data, "mode", "harness"), HARNESS_MODES, "harness.mode")
    path_value = _optional_str(data.get("path"), "harness.path")
    path = None if path_value is None else _config_path(path_value, base_dir)
    config = _optional_dict(data.get("config"), "harness.config")

    if harness_type == "submission":
        if mode != "submission":
            raise ConfigError("harness.type 'submission' requires mode 'submission'")
        if path is None:
            raise ConfigError("harness.path is required for submission harnesses")
    else:
        if mode == "submission":
            raise ConfigError("harness.mode 'submission' requires harness.type 'submission'")
        if mode == "mounted" and harness_type != "codex":
            raise ConfigError("harness.mode 'mounted' requires harness.type 'codex'")
        if path is not None:
            raise ConfigError("harness.path is only supported for submission harnesses")

    return TesterHarnessSection(
        type=harness_type,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        env=_env_names(data.get("env"), "harness.env"),
        path=path,
        config=config,
    )


def _required_dict(data: dict[str, Any], key: str, section: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{section}.{key} must be an object")
    return value


def _optional_dict(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{field} must be an object")
    return dict(value)


def _required_str(data: dict[str, Any], key: str, section: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{section}.{key} must be a non-empty string")
    return value


def _optional_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a non-empty string")
    return value


def _env_names(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"{field} must be a list of non-empty environment variable names")
    names = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item or "=" in item:
            raise ConfigError(f"{field}[{index}] must be a non-empty environment variable name without '='")
        names.append(item)
    return tuple(names)


def _config_path(value: str, base_dir: Path | None) -> Path:
    path = Path(value)
    if base_dir is not None and not path.is_absolute():
        return base_dir / path
    return path


def _expect_literal(value: str, allowed: set[str], field: str) -> str:
    if value not in allowed:
        expected = ", ".join(sorted(allowed))
        raise ConfigError(f"{field} must be one of: {expected}")
    return value


def _reject_unknown_fields(data: dict[str, Any], allowed: set[str], section: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        names = ", ".join(unknown)
        raise ConfigError(f"{section} contains unsupported field(s): {names}")
