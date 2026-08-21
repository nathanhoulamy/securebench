"""Tester-owned benchmark-pack execution config loading."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from securebench.data_formats import DuplicateYamlKeyError, strict_yaml_loads
from securebench.errors import ConfigError


SUPPORTED_TESTER_SCHEMA_VERSION = "1.0"
HarnessType = Literal["codex", "claude_code", "command"]

ROOT_FIELDS = {"schema_version", "run", "benchmark", "harness", "docker"}
RUN_FIELDS = {"id", "output_dir", "max_workers"}
BENCHMARK_FIELDS = {"manifest", "tasks"}
HARNESS_FIELDS = {"type", "env", "config"}
DOCKER_FIELDS = {"max_cached_images", "overlay_workspace_bytes"}
HARNESS_TYPES = {"codex", "claude_code", "command"}
ENVIRONMENT_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
MAX_RUN_ID_LENGTH = 256
MAX_TESTER_CONFIG_BYTES = 1024 * 1024
MIN_OVERLAY_WORKSPACE_BYTES = 64 * 1024 * 1024
MAX_OVERLAY_WORKSPACE_BYTES = 16 * 1024 * 1024 * 1024 * 1024
OVERLAY_WORKSPACE_BLOCK_BYTES = 4096


@dataclass(frozen=True)
class TesterRunSection:
    """One tester-owned execution identity and output location."""

    id: str
    output_dir: Path
    max_workers: int = 1


@dataclass(frozen=True)
class TesterBenchmarkSection:
    """Benchmark pack files selected for this execution."""

    manifest: Path
    tasks: Path


@dataclass(frozen=True)
class TesterHarnessSection:
    """Candidate-producing harness selected by the tester."""

    type: HarnessType
    env: tuple[str, ...] = ()
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TesterDockerSection:
    """Docker retention and hard workspace capacities for one tester run."""

    max_cached_images: int | None = None
    overlay_workspace_bytes: int | None = None


@dataclass(frozen=True)
class TesterConfig:
    """Parsed tester YAML for a benchmark-pack run."""

    schema_version: str
    run: TesterRunSection
    benchmark: TesterBenchmarkSection
    harness: TesterHarnessSection
    docker: TesterDockerSection = field(default_factory=TesterDockerSection)


def load_tester_config(path: str | Path) -> TesterConfig:
    """Load a tester config from a YAML file."""
    config_path = Path(path)
    try:
        with config_path.open("rb") as stream:
            config_bytes = stream.read(MAX_TESTER_CONFIG_BYTES + 1)
    except OSError as exc:
        raise ConfigError("Unable to read tester config") from exc
    if len(config_bytes) > MAX_TESTER_CONFIG_BYTES:
        raise ConfigError("Tester config exceeds its size bound")
    try:
        config_text = config_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise ConfigError("Tester config is not valid UTF-8") from exc
    try:
        loaded = strict_yaml_loads(config_text)
    except DuplicateYamlKeyError as exc:
        raise ConfigError("Tester config contains a duplicate mapping key") from exc
    except yaml.YAMLError as exc:
        raise ConfigError("Tester config is not valid YAML") from exc
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
    run_id = _required_str(run_data, "id", "run")
    if len(run_id) > MAX_RUN_ID_LENGTH:
        raise ConfigError(f"run.id must be at most {MAX_RUN_ID_LENGTH} characters")
    run = TesterRunSection(
        id=run_id,
        output_dir=_config_path(_required_str(run_data, "output_dir", "run"), base),
        max_workers=_positive_int(run_data.get("max_workers", 1), "run.max_workers"),
    )
    benchmark = TesterBenchmarkSection(
        manifest=_config_path(_required_str(benchmark_data, "manifest", "benchmark"), base),
        tasks=_config_path(_required_str(benchmark_data, "tasks", "benchmark"), base),
    )
    harness = _harness_section(harness_data)
    return TesterConfig(
        schema_version=schema_version,
        run=run,
        benchmark=benchmark,
        harness=harness,
        docker=_docker_section(data.get("docker")),
    )


def _harness_section(data: dict[str, Any]) -> TesterHarnessSection:
    harness_type = _expect_literal(_required_str(data, "type", "harness"), HARNESS_TYPES, "harness.type")
    config = _optional_dict(data.get("config"), "harness.config")

    return TesterHarnessSection(
        type=harness_type,  # type: ignore[arg-type]
        env=_env_names(data.get("env"), "harness.env"),
        config=config,
    )


def _docker_section(value: Any) -> TesterDockerSection:
    data = _optional_dict(value, "docker")
    _reject_unknown_fields(data, DOCKER_FIELDS, "docker")
    max_cached_images = data.get("max_cached_images")
    if max_cached_images is not None and (
        isinstance(max_cached_images, bool)
        or not isinstance(max_cached_images, int)
        or max_cached_images <= 0
    ):
        raise ConfigError("docker.max_cached_images must be a positive integer")
    overlay_workspace_bytes = data.get("overlay_workspace_bytes")
    if overlay_workspace_bytes is not None:
        overlay_workspace_bytes = _positive_int(
            overlay_workspace_bytes,
            "docker.overlay_workspace_bytes",
        )
        if not (
            MIN_OVERLAY_WORKSPACE_BYTES
            <= overlay_workspace_bytes
            <= MAX_OVERLAY_WORKSPACE_BYTES
        ):
            raise ConfigError(
                "docker.overlay_workspace_bytes must be between "
                f"{MIN_OVERLAY_WORKSPACE_BYTES} and {MAX_OVERLAY_WORKSPACE_BYTES}"
            )
        if overlay_workspace_bytes % OVERLAY_WORKSPACE_BLOCK_BYTES:
            raise ConfigError(
                "docker.overlay_workspace_bytes must be a multiple of "
                f"{OVERLAY_WORKSPACE_BLOCK_BYTES}"
            )
    return TesterDockerSection(
        max_cached_images=max_cached_images,
        overlay_workspace_bytes=overlay_workspace_bytes,
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


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{field} must be a positive integer")
    return value


def _env_names(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"{field} must be a list of non-empty environment variable names")
    names = []
    seen = set()
    for index, item in enumerate(value):
        if not isinstance(item, str) or not ENVIRONMENT_NAME_RE.fullmatch(item):
            raise ConfigError(f"{field}[{index}] must be a valid environment variable name")
        if item in seen:
            raise ConfigError(f"{field} contains duplicate environment variable name: {item}")
        seen.add(item)
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
