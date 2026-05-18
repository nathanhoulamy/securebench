"""Benchmark pack loading for manifest-plus-row datasets."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

import yaml

from securebench.errors import ConfigError


DEFAULT_PUBLIC_ASSET_ROOT = "assets/"
DEFAULT_EVAL_ASSET_ROOT = "hidden/"


@dataclass(frozen=True)
class BenchmarkDefaults:
    """Shared defaults applied to benchmark task rows."""

    family: str | None = None
    environment: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetRoots:
    """Source roots used to locate benchmark-pack assets."""

    public: str = DEFAULT_PUBLIC_ASSET_ROOT
    eval: str = DEFAULT_EVAL_ASSET_ROOT


@dataclass(frozen=True)
class AssetDefaults:
    """Default placement behavior for task assets."""

    read_only: bool = True


@dataclass(frozen=True)
class BenchmarkPackManifest:
    """Benchmark-pack manifest with shared row defaults."""

    id: str
    version: int
    defaults: BenchmarkDefaults = field(default_factory=BenchmarkDefaults)
    asset_roots: AssetRoots = field(default_factory=AssetRoots)
    asset_defaults: AssetDefaults = field(default_factory=AssetDefaults)
    path: Path | None = None


@dataclass(frozen=True)
class BenchmarkTaskRow:
    """One author-facing task row after common manifest defaults are applied."""

    id: str
    family: str
    input: dict[str, Any] = field(default_factory=dict)
    assets: tuple[dict[str, Any], ...] = ()
    eval: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkPack:
    """A benchmark manifest plus task-row file."""

    manifest: BenchmarkPackManifest
    tasks_path: Path

    def iter_rows(self, *, limit: int | None = None) -> Iterator[BenchmarkTaskRow]:
        """Yield task rows with manifest defaults applied."""
        yielded = 0
        for line_number, line in _iter_jsonl_lines(self.tasks_path):
            if limit is not None and yielded >= limit:
                break
            row = _load_jsonl_object(self.tasks_path, line_number, line)
            yield parse_task_row(row, manifest=self.manifest, line_number=line_number)
            yielded += 1

    def load_rows(self, *, limit: int | None = None) -> list[BenchmarkTaskRow]:
        """Load task rows eagerly into a list."""
        return list(self.iter_rows(limit=limit))


def load_benchmark_manifest(path: str | Path) -> BenchmarkPackManifest:
    """Load and validate a benchmark-pack manifest YAML file."""
    manifest_path = Path(path)
    loaded = yaml.safe_load(manifest_path.read_text())
    if not isinstance(loaded, dict):
        raise ConfigError("Benchmark manifest root must be an object")
    return parse_benchmark_manifest(loaded, path=manifest_path)


def parse_benchmark_manifest(
    data: dict[str, Any],
    *,
    path: Path | None = None,
) -> BenchmarkPackManifest:
    """Parse and validate a benchmark-pack manifest object."""
    manifest_id = _required_str(data, "id", "manifest")
    version = _required_int(data, "version", "manifest")
    defaults = _benchmark_defaults(data.get("defaults"))
    asset_roots = _asset_roots(data.get("asset_roots"))
    asset_defaults = _asset_defaults(data.get("asset_defaults"))
    return BenchmarkPackManifest(
        id=manifest_id,
        version=version,
        defaults=defaults,
        asset_roots=asset_roots,
        asset_defaults=asset_defaults,
        path=path,
    )


def load_benchmark_pack(manifest_path: str | Path, tasks_path: str | Path) -> BenchmarkPack:
    """Load a benchmark-pack manifest and bind it to a JSONL task-row file."""
    return BenchmarkPack(
        manifest=load_benchmark_manifest(manifest_path),
        tasks_path=Path(tasks_path),
    )


def parse_task_row(
    row: dict[str, Any],
    *,
    manifest: BenchmarkPackManifest,
    line_number: int | None = None,
) -> BenchmarkTaskRow:
    """Normalize one author-facing task row using manifest defaults."""
    context = "task row" if line_number is None else f"task row line {line_number}"
    task_id = _required_str(row, "id", context)
    family = _optional_str(row.get("family"), f"{context}.family")
    if family is None:
        family = manifest.defaults.family
    if family is None:
        raise ConfigError(f"{context}.family is required when manifest defaults.family is not set")

    input_data = _optional_dict(row.get("input"), f"{context}.input")
    eval_data = _optional_dict(row.get("eval"), f"{context}.eval")
    metadata = _optional_dict(row.get("metadata"), f"{context}.metadata")
    environment = {
        **manifest.defaults.environment,
        **_optional_dict(row.get("environment"), f"{context}.environment"),
    }
    assets = _assets(row.get("assets"), f"{context}.assets")

    return BenchmarkTaskRow(
        id=task_id,
        family=family,
        input=input_data,
        assets=assets,
        eval=eval_data,
        environment=environment,
        metadata=metadata,
    )


def _benchmark_defaults(value: Any) -> BenchmarkDefaults:
    if value is None:
        return BenchmarkDefaults()
    if not isinstance(value, dict):
        raise ConfigError("manifest.defaults must be an object")
    return BenchmarkDefaults(
        family=_optional_str(value.get("family"), "manifest.defaults.family"),
        environment=_optional_dict(value.get("environment"), "manifest.defaults.environment"),
    )


def _asset_roots(value: Any) -> AssetRoots:
    if value is None:
        return AssetRoots()
    if not isinstance(value, dict):
        raise ConfigError("manifest.asset_roots must be an object")
    return AssetRoots(
        public=_asset_root(value.get("public", DEFAULT_PUBLIC_ASSET_ROOT), "manifest.asset_roots.public"),
        eval=_asset_root(value.get("eval", DEFAULT_EVAL_ASSET_ROOT), "manifest.asset_roots.eval"),
    )


def _asset_defaults(value: Any) -> AssetDefaults:
    if value is None:
        return AssetDefaults()
    if not isinstance(value, dict):
        raise ConfigError("manifest.asset_defaults must be an object")
    read_only = value.get("read_only", True)
    if not isinstance(read_only, bool):
        raise ConfigError("manifest.asset_defaults.read_only must be a boolean")
    return AssetDefaults(read_only=read_only)


def _assets(value: Any, field: str) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"{field} must be a list")
    assets: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"{field}[{index}] must be an object")
        assets.append(dict(item))
    return tuple(assets)


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


def _required_int(data: dict[str, Any], key: str, section: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{section}.{key} must be an integer")
    return value


def _asset_root(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{field} must be a non-empty relative path")
    if "\\" in value:
        raise ConfigError(f"{field} may not contain backslashes")
    candidate = PurePosixPath(value)
    if candidate.is_absolute():
        raise ConfigError(f"{field} may not be absolute")
    if ".." in candidate.parts:
        raise ConfigError(f"{field} may not contain '..'")
    if str(candidate) in ("", "."):
        raise ConfigError(f"{field} must be a non-empty relative path")
    return value


def _iter_jsonl_lines(path: Path) -> Iterator[tuple[int, str]]:
    with path.open() as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if stripped:
                yield line_number, stripped


def _load_jsonl_object(path: Path, line_number: int, line: str) -> dict[str, Any]:
    try:
        loaded = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path}:{line_number}: task row must be an object")
    return loaded
