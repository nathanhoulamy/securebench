"""Compile strict benchmark rows into component-safe tasks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Iterator

from securebench.benchmark_pack import BenchmarkPack
from securebench.errors import ConfigError
from securebench.resources import Resource, ResourceBundle
from securebench.schemas.benchmark import BenchmarkPackManifestV2, BenchmarkRowV2
from securebench.tasks import BenchmarkTask


def compile_benchmark_row(
    row: BenchmarkRowV2,
    *,
    manifest: BenchmarkPackManifestV2,
    manifest_path: str | Path,
) -> BenchmarkTask:
    """Resolve one validated row without weakening its visibility lanes."""
    manifest_file = Path(manifest_path).resolve()
    pack_root = manifest_file.parent
    roots = _resolved_resource_roots(pack_root, manifest)
    resources: dict[str, Resource] = {}

    for name, value in row.input.items():
        _add_resource(
            resources,
            Resource(
                name=f"input.{name}",
                value=value,
                visibility="public",
                kind="text" if isinstance(value, str) else "json",
            ),
        )

    for index, asset in enumerate(row.assets):
        source, kind = _resolve_pack_resource(roots["public"], asset.path, f"assets[{index}]")
        _add_resource(
            resources,
            Resource(
                name=f"asset.{index}",
                value={
                    "source_path": str(source),
                    "mount": asset.mount,
                    "read_only": asset.read_only,
                },
                visibility="public",
                kind=kind,
            ),
        )

    for identifier, resource in row.verification.resources.runtime.items():
        source, kind = _resolve_pack_resource(
            roots["runtime"],
            resource.path,
            f"verification.resources.runtime.{identifier}",
        )
        _add_resource(
            resources,
            Resource(
                name=f"runtime.{identifier}",
                value={
                    "source_path": str(source),
                    "mount": resource.mount,
                    "read_only": True,
                },
                visibility="evaluation_inputs",
                kind=kind,
            ),
        )

    for identifier, resource in row.verification.resources.host.items():
        source, kind = _resolve_pack_resource(
            roots["host"],
            resource.path,
            f"verification.resources.host.{identifier}",
        )
        _add_resource(
            resources,
            Resource(
                name=f"host.{identifier}",
                value={"source_path": str(source)},
                visibility="hidden",
                kind=kind,
            ),
        )

    manifest_bytes = manifest_file.read_bytes()
    row_bytes = json.dumps(
        row.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return BenchmarkTask(
        id=row.id,
        benchmark_id=manifest.id,
        family=row.family,
        input=dict(row.input),
        assets=tuple(row.assets),
        environment=row.environment,
        verification=row.verification,
        metadata=dict(row.metadata),
        resources=ResourceBundle(resources),
        pack_root=pack_root,
        manifest_path=manifest_file,
        manifest_digest="sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),
        row_digest="sha256:" + hashlib.sha256(row_bytes).hexdigest(),
    )


def compile_benchmark_pack(
    pack: BenchmarkPack,
    *,
    limit: int | None = None,
) -> Iterator[BenchmarkTask]:
    """Compile selected rows with pack-root and symlink enforcement."""
    _validate_pack_root(pack.root)
    for row in pack.iter_rows(limit=limit):
        yield compile_benchmark_row(
            row,
            manifest=pack.manifest,
            manifest_path=pack.manifest_path,
        )


def _resolved_resource_roots(
    pack_root: Path,
    manifest: BenchmarkPackManifestV2,
) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for name, value in manifest.resource_roots.model_dump().items():
        unresolved = pack_root.joinpath(*PurePosixPath(value).parts)
        _reject_symlink_components(pack_root, unresolved, f"resource_roots.{name}")
        resolved = unresolved.resolve()
        if not resolved.is_relative_to(pack_root):
            raise ConfigError(f"resource_roots.{name} escapes the benchmark pack")
        if not resolved.is_dir():
            raise ConfigError(f"resource_roots.{name} directory does not exist: {value}")
        roots[name] = resolved
    return roots


def _validate_pack_root(pack_root: Path) -> None:
    if not pack_root.is_dir():
        raise ConfigError(f"benchmark pack directory does not exist: {pack_root}")


def _resolve_pack_resource(root: Path, value: str, field: str) -> tuple[Path, str]:
    unresolved = root.joinpath(*PurePosixPath(value).parts)
    _reject_symlink_components(root, unresolved, field)
    resolved = unresolved.resolve()
    if not resolved.is_relative_to(root):
        raise ConfigError(f"{field} escapes its visibility source root")
    if resolved.is_file():
        return resolved, "file"
    if resolved.is_dir():
        for child in resolved.rglob("*"):
            if child.is_symlink():
                raise ConfigError(f"{field} directory may not contain symlinks: {child}")
        return resolved, "directory"
    raise ConfigError(f"{field} source does not exist or is not a regular file/directory: {value}")


def _reject_symlink_components(root: Path, target: Path, field: str) -> None:
    current = root
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ConfigError(f"{field} escapes the benchmark pack") from exc
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ConfigError(f"{field} may not traverse symlink: {current}")
        if not current.exists():
            break


def _add_resource(resources: dict[str, Resource], resource: Resource) -> None:
    if resource.name in resources:
        raise ConfigError(f"duplicate compiled resource name: {resource.name}")
    resources[resource.name] = resource
