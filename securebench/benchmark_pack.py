"""Strict v2 benchmark-pack loading."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml
from pydantic import ValidationError

from securebench.errors import ConfigError
from securebench.schemas.benchmark import (
    BenchmarkPackManifestV2,
    BenchmarkRowDocumentV2,
    BenchmarkRowV2,
    normalize_benchmark_row,
)


@dataclass(frozen=True)
class BenchmarkPack:
    """A validated v2 manifest bound to its JSONL row file."""

    manifest: BenchmarkPackManifestV2
    manifest_path: Path
    tasks_path: Path

    @property
    def root(self) -> Path:
        return self.manifest_path.resolve().parent

    def iter_rows(self, *, limit: int | None = None) -> Iterator[BenchmarkRowV2]:
        yielded = 0
        seen_ids: set[str] = set()
        for line_number, line in _iter_jsonl_lines(self.tasks_path):
            if limit is not None and yielded >= limit:
                break
            raw = _load_jsonl_object(self.tasks_path, line_number, line)
            row = parse_benchmark_row(raw, manifest=self.manifest, line_number=line_number)
            if row.id in seen_ids:
                raise ConfigError(f"benchmark row line {line_number}: duplicate row id {row.id!r}")
            seen_ids.add(row.id)
            yield row
            yielded += 1

    def load_rows(self, *, limit: int | None = None) -> list[BenchmarkRowV2]:
        return list(self.iter_rows(limit=limit))


def parse_benchmark_manifest(data: dict[str, Any]) -> BenchmarkPackManifestV2:
    """Parse a closed v2 manifest; legacy fields are schema errors."""
    try:
        return BenchmarkPackManifestV2.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_pydantic_error("benchmark manifest", exc)) from exc


def load_benchmark_manifest(path: str | Path) -> BenchmarkPackManifestV2:
    manifest_path = Path(path)
    loaded = yaml.safe_load(manifest_path.read_text())
    if not isinstance(loaded, dict):
        raise ConfigError("Benchmark manifest root must be an object")
    return parse_benchmark_manifest(loaded)


def parse_benchmark_row(
    row: dict[str, Any],
    *,
    manifest: BenchmarkPackManifestV2,
    line_number: int | None = None,
) -> BenchmarkRowV2:
    """Parse one row and apply manifest defaults."""
    context = "benchmark row" if line_number is None else f"benchmark row line {line_number}"
    try:
        document = BenchmarkRowDocumentV2.model_validate(row)
        return normalize_benchmark_row(document, manifest)
    except (ValidationError, ValueError) as exc:
        message = (
            _pydantic_error(context, exc)
            if isinstance(exc, ValidationError)
            else f"{context}: {exc}"
        )
        raise ConfigError(message) from exc


def load_benchmark_pack(manifest_path: str | Path, tasks_path: str | Path) -> BenchmarkPack:
    manifest_file = Path(manifest_path)
    return BenchmarkPack(
        manifest=load_benchmark_manifest(manifest_file),
        manifest_path=manifest_file,
        tasks_path=Path(tasks_path),
    )


def _iter_jsonl_lines(path: Path) -> Iterator[tuple[int, str]]:
    try:
        file = path.open()
    except OSError as exc:
        raise ConfigError(f"Unable to read benchmark rows {path}: {exc}") from exc
    with file:
        for line_number, line in enumerate(file, start=1):
            if line.strip():
                yield line_number, line


def _load_jsonl_object(path: Path, line_number: int, line: str) -> dict[str, Any]:
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path} line {line_number}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"Benchmark row in {path} line {line_number} must be an object")
    return value


def _pydantic_error(context: str, exc: ValidationError) -> str:
    first = exc.errors(include_url=False)[0]
    location = ".".join(str(part) for part in first.get("loc", ()))
    field = f".{location}" if location else ""
    return f"{context}{field}: {first.get('msg', 'invalid value')}"
