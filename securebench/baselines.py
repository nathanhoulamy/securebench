"""Deterministic identity for the candidate-visible baseline contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from securebench.tasks import BenchmarkTask


def task_baseline_digest(task: BenchmarkTask) -> str:
    """Hash the immutable image, row, and actual public asset content."""
    assets: list[dict[str, object]] = []
    for resource in task.resources.by_visibility("public"):
        if resource.kind not in {"file", "directory"}:
            continue
        descriptor = resource.value
        if not isinstance(descriptor, dict):
            raise ValueError(f"compiled public resource {resource.name!r} is invalid")
        source = descriptor.get("source_path")
        if not isinstance(source, str):
            raise ValueError(f"compiled public resource {resource.name!r} has no source_path")
        assets.append(
            {
                "name": resource.name,
                "mount": descriptor.get("mount"),
                "read_only": descriptor.get("read_only"),
                "content_digest": _path_digest(Path(source)),
            }
        )
    document = {
        "schema_version": "1",
        "manifest_digest": task.manifest_digest,
        "row_digest": task.row_digest,
        "image": task.environment.image,
        "workdir": task.environment.workdir,
        "assets": assets,
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _path_digest(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file() and not path.is_symlink():
        digest.update(b"file\0")
        _hash_file(digest, path)
        return "sha256:" + digest.hexdigest()
    if path.is_dir() and not path.is_symlink():
        digest.update(b"directory\0")
        for child in sorted(path.rglob("*"), key=lambda value: value.relative_to(path).as_posix()):
            relative = child.relative_to(path).as_posix().encode()
            if child.is_symlink():
                raise ValueError(f"compiled public directory contains a symlink: {child}")
            if child.is_dir():
                digest.update(b"d\0" + relative + b"\0")
            elif child.is_file():
                digest.update(b"f\0" + relative + b"\0")
                _hash_file(digest, child)
            else:
                raise ValueError(f"compiled public directory contains a special file: {child}")
        return "sha256:" + digest.hexdigest()
    raise ValueError(f"compiled public resource disappeared: {path}")


def _hash_file(digest: Any, path: Path) -> None:
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
