"""Bounded passive observation of hostile files and directory trees."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from securebench.schemas.benchmark import ArtifactLimits
from securebench.verification.json_data import canonical_json_bytes
from securebench.verification.models import CandidateObservationError


MAX_OBSERVED_PATH_BYTES = 4096
MAX_OBSERVED_PATH_DEPTH = 64


@dataclass(frozen=True)
class PassiveFileObservation:
    """One bounded filesystem value ready for a registered passive parser."""

    kind: str
    digest: str
    size: int
    value: bytes | dict[str, Any]


def observe_bounded_path(
    root: Path,
    source_path: str,
    limits: ArtifactLimits,
    *,
    subject: str,
) -> PassiveFileObservation:
    """Observe one contained path without following candidate-created symlinks."""
    relative = PurePosixPath(source_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.parts
        or "\\" in source_path
        or "\x00" in source_path
    ):
        raise CandidateObservationError(
            "artifact_path_escape", f"{subject} path is not safely contained"
        )
    _validate_relative_path(relative, subject=subject)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("passive observation root must be one real directory")
    target = root.joinpath(*relative.parts)
    _validate_real_parent(root, relative, subject=subject)
    try:
        info = target.lstat()
    except OSError as exc:
        raise CandidateObservationError(
            "artifact_missing", f"{subject} is missing"
        ) from exc
    if limits.max_bytes is not None:
        if not stat.S_ISREG(info.st_mode):
            raise CandidateObservationError(
                "artifact_wrong_type", f"{subject} is not a regular file"
            )
        if info.st_size > limits.max_bytes:
            raise CandidateObservationError(
                "artifact_too_large", f"{subject} exceeds its byte bound"
            )
        content = _read_bounded_regular_file(target, info, maximum=limits.max_bytes)
        return PassiveFileObservation(
            kind="regular_file",
            digest="sha256:" + hashlib.sha256(content).hexdigest(),
            size=len(content),
            value=content,
        )
    if not stat.S_ISDIR(info.st_mode):
        raise CandidateObservationError(
            "artifact_wrong_type", f"{subject} is not a directory tree"
        )
    maximum_files = limits.max_files
    maximum_bytes = limits.max_total_bytes
    if maximum_files is None or maximum_bytes is None:
        raise ValueError("tree observation requires complete tree limits")
    nodes, total_bytes = _bounded_tree(
        target,
        maximum_files=maximum_files,
        maximum_bytes=maximum_bytes,
        subject=subject,
    )
    value = {"nodes": nodes}
    return PassiveFileObservation(
        kind="directory_tree",
        digest="sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest(),
        size=total_bytes,
        value=value,
    )


def _read_bounded_regular_file(
    path: Path,
    before: os.stat_result,
    *,
    maximum: int,
) -> bytes:
    flags = os.O_RDONLY | (os.O_NOFOLLOW if hasattr(os, "O_NOFOLLOW") else 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise CandidateObservationError(
            "artifact_unreadable", "Candidate artifact could not be read safely"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if _stat_identity(opened) != _stat_identity(before) or not stat.S_ISREG(opened.st_mode):
            raise CandidateObservationError(
                "artifact_changed", "Candidate artifact changed during passive observation"
            )
        content = bytearray()
        while len(content) <= maximum:
            try:
                chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - len(content)))
            except OSError as exc:
                raise CandidateObservationError(
                    "artifact_unreadable", "Candidate artifact could not be read safely"
                ) from exc
            if not chunk:
                break
            content.extend(chunk)
        after_read = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if len(content) > maximum:
        raise CandidateObservationError(
            "artifact_too_large", "Candidate artifact exceeds its byte bound"
        )
    try:
        after_path = path.lstat()
    except OSError as exc:
        raise CandidateObservationError(
            "artifact_changed", "Candidate artifact changed during passive observation"
        ) from exc
    if (
        _stat_identity(after_read) != _stat_identity(opened)
        or _stat_identity(after_path) != _stat_identity(opened)
    ):
        raise CandidateObservationError(
            "artifact_changed", "Candidate artifact changed during passive observation"
        )
    return bytes(content)


def _bounded_tree(
    root: Path,
    *,
    maximum_files: int,
    maximum_bytes: int,
    subject: str,
) -> tuple[list[dict[str, Any]], int]:
    nodes: list[dict[str, Any]] = []
    total_bytes = 0
    pending = [root]
    while pending:
        current = pending.pop()
        directories: list[Path] = []
        try:
            with os.scandir(current) as entries:
                children = []
                remaining = maximum_files - len(nodes)
                for entry in entries:
                    if len(children) >= remaining:
                        raise CandidateObservationError(
                            "artifact_too_large",
                            f"{subject} tree exceeds its entry bound",
                        )
                    children.append(entry)
                children.sort(
                    key=lambda item: item.name.encode("utf-8", errors="surrogateescape")
                )
        except CandidateObservationError:
            raise
        except OSError as exc:
            raise CandidateObservationError(
                "artifact_unreadable", f"{subject} tree is inaccessible"
            ) from exc
        for child in children:
            path = Path(child.path)
            relative = PurePosixPath(path.relative_to(root).as_posix())
            _validate_relative_path(relative, subject=subject)
            try:
                info = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise CandidateObservationError(
                    "artifact_unreadable", f"{subject} tree is inaccessible"
                ) from exc
            node: dict[str, Any] = {"path": str(relative)}
            if stat.S_ISDIR(info.st_mode):
                node.update({"kind": "directory", "mode": 0o755})
                directories.append(path)
            elif stat.S_ISREG(info.st_mode):
                if total_bytes + info.st_size > maximum_bytes:
                    raise CandidateObservationError(
                        "artifact_too_large", f"{subject} tree exceeds its byte bound"
                    )
                content = _read_bounded_regular_file(
                    path,
                    info,
                    maximum=maximum_bytes - total_bytes,
                )
                total_bytes += len(content)
                node.update(
                    {
                        "kind": "regular_file",
                        "mode": 0o755 if info.st_mode & 0o111 else 0o644,
                        "size": len(content),
                        "blob": "sha256:" + hashlib.sha256(content).hexdigest(),
                    }
                )
            elif stat.S_ISLNK(info.st_mode):
                try:
                    target = os.readlink(path)
                    target_bytes = target.encode("utf-8", errors="strict")
                except (OSError, UnicodeError) as exc:
                    raise CandidateObservationError(
                        "artifact_unreadable", f"{subject} contains an invalid symlink"
                    ) from exc
                _validate_tree_symlink(str(relative), target, subject=subject)
                total_bytes += len(target_bytes)
                if total_bytes > maximum_bytes:
                    raise CandidateObservationError(
                        "artifact_too_large", f"{subject} tree exceeds its byte bound"
                    )
                node.update({"kind": "symlink", "target": target})
            else:
                raise CandidateObservationError(
                    "artifact_wrong_type", f"{subject} tree contains a special file"
                )
            nodes.append(node)
        pending.extend(reversed(directories))
    nodes.sort(key=lambda value: value["path"].encode("utf-8"))
    return nodes, total_bytes


def _validate_relative_path(path: PurePosixPath, *, subject: str) -> None:
    try:
        encoded = str(path).encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise CandidateObservationError(
            "artifact_unreadable", f"{subject} contains a non-UTF-8 path"
        ) from exc
    if len(encoded) > MAX_OBSERVED_PATH_BYTES or len(path.parts) > MAX_OBSERVED_PATH_DEPTH:
        raise CandidateObservationError(
            "artifact_too_large", f"{subject} contains a path outside framework bounds"
        )


def _validate_real_parent(root: Path, path: PurePosixPath, *, subject: str) -> None:
    current = root
    for part in path.parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise CandidateObservationError(
                "artifact_missing", f"{subject} is missing"
            ) from exc
        if stat.S_ISLNK(info.st_mode):
            raise CandidateObservationError(
                "artifact_path_escape", f"{subject} path contains a symlinked parent"
            )
        if not stat.S_ISDIR(info.st_mode):
            raise CandidateObservationError(
                "artifact_wrong_type", f"{subject} parent is not a directory"
            )


def _validate_tree_symlink(path: str, target: str, *, subject: str) -> None:
    target_path = PurePosixPath(target)
    if target_path.is_absolute() or "\\" in target or "\x00" in target:
        raise CandidateObservationError(
            "artifact_path_escape", f"{subject} symlink escapes its tree: {path}"
        )
    stack = list(PurePosixPath(path).parent.parts)
    for part in target_path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not stack:
                raise CandidateObservationError(
                    "artifact_path_escape", f"{subject} symlink escapes its tree: {path}"
                )
            stack.pop()
        else:
            stack.append(part)


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
    )
