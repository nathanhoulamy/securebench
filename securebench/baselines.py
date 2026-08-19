"""Deterministic identities for candidate and verification inputs."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from securebench.resources import ResourceBundle
from securebench.tasks import BenchmarkTask


def task_baseline_digest(task: BenchmarkTask) -> str:
    """Hash the immutable image, row, and actual public asset content."""
    return baseline_digest(
        resources=task.resources,
        manifest_digest=task.manifest_digest,
        row_digest=task.row_digest,
        image=task.environment.image,
        workdir=task.environment.workdir,
    )


def baseline_digest(
    *,
    resources: ResourceBundle,
    manifest_digest: str,
    row_digest: str,
    image: str,
    workdir: str,
) -> str:
    """Hash a compiled candidate-visible baseline without requiring a task."""
    assets: list[dict[str, object]] = []
    for resource in resources.by_visibility("public"):
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
                "content_digest": path_digest(Path(source)),
            }
        )
    document = {
        "schema_version": "1",
        "manifest_digest": manifest_digest,
        "row_digest": row_digest,
        "image": image,
        "workdir": workdir,
        "assets": assets,
    }
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def task_verification_digest(task: BenchmarkTask) -> str:
    """Hash the actual runtime and host resources used to verify one row."""
    return verification_digest(
        resources=task.resources,
        manifest_digest=task.manifest_digest,
        row_digest=task.row_digest,
    )


def verification_digest(
    *,
    resources: ResourceBundle,
    manifest_digest: str,
    row_digest: str,
) -> str:
    """Hash compiled runtime and host inputs without requiring a task."""
    resource_digests: list[dict[str, object]] = []
    for visibility in ("evaluation_inputs", "hidden"):
        for resource in sorted(
            resources.by_visibility(visibility),
            key=lambda item: item.name,
        ):
            if resource.kind not in {"file", "directory"}:
                continue
            descriptor = resource.value
            if not isinstance(descriptor, dict):
                raise ValueError(f"compiled verification resource {resource.name!r} is invalid")
            source = descriptor.get("source_path")
            if not isinstance(source, str):
                raise ValueError(
                    f"compiled verification resource {resource.name!r} has no source_path"
                )
            resource_digests.append(
                {
                    "name": resource.name,
                    "visibility": visibility,
                    "content_digest": path_digest(Path(source)),
                }
            )
    document = {
        "schema_version": "1",
        "manifest_digest": manifest_digest,
        "row_digest": row_digest,
        "resources": resource_digests,
    }
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def path_digest(path: Path) -> str:
    """Hash the contents and permission bits of a symlink-free path."""
    digest = hashlib.sha256()
    try:
        root_info = path.lstat()
    except OSError as exc:
        raise ValueError(f"compiled resource disappeared: {path}") from exc
    if stat.S_ISREG(root_info.st_mode):
        digest.update(b"file\0")
        _hash_mode(digest, root_info.st_mode)
        _hash_file(digest, path, root_info)
        return "sha256:" + digest.hexdigest()
    if stat.S_ISDIR(root_info.st_mode):
        digest.update(b"directory\0")
        _hash_mode(digest, root_info.st_mode)
        for child in sorted(path.rglob("*"), key=lambda value: value.relative_to(path).as_posix()):
            relative = child.relative_to(path).as_posix().encode()
            try:
                child_info = child.lstat()
            except OSError as exc:
                raise ValueError(f"compiled resource changed while hashing: {child}") from exc
            if stat.S_ISLNK(child_info.st_mode):
                raise ValueError(f"compiled resource directory contains a symlink: {child}")
            if stat.S_ISDIR(child_info.st_mode):
                digest.update(b"d\0" + relative + b"\0")
                _hash_mode(digest, child_info.st_mode)
            elif stat.S_ISREG(child_info.st_mode):
                digest.update(b"f\0" + relative + b"\0")
                _hash_mode(digest, child_info.st_mode)
                _hash_file(digest, child, child_info)
            else:
                raise ValueError(f"compiled resource directory contains a special file: {child}")
        return "sha256:" + digest.hexdigest()
    raise ValueError(f"compiled resource disappeared: {path}")


def _hash_mode(digest: Any, mode: int) -> None:
    digest.update(f"{stat.S_IMODE(mode):04o}\0".encode("ascii"))


def _hash_file(digest: Any, path: Path, before: os.stat_result) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"compiled resource changed while hashing: {path}") from exc
    try:
        opened = os.fstat(descriptor)
        if _stat_identity(opened) != _stat_identity(before):
            raise ValueError(f"compiled resource changed while hashing: {path}")
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
    finally:
        os.close(descriptor)
    try:
        after = path.lstat()
    except OSError as exc:
        raise ValueError(f"compiled resource changed while hashing: {path}") from exc
    if _stat_identity(after) != _stat_identity(before):
        raise ValueError(f"compiled resource changed while hashing: {path}")


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
    )
