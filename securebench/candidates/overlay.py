"""Canonical scanning and transactional capture for filesystem overlays."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import stat
import sys
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from securebench.candidates.models import (
    CandidateCaptureError,
    CandidateStoreError,
    StoredCandidate,
)
from securebench.candidates.store import (
    CandidateStore,
    CandidateStoreCapacityError,
    CandidateStoreTransaction,
)
from securebench.path_safety import portable_path_text, portable_paths_overlap
from securebench.schemas.benchmark import (
    FILESYSTEM_OVERLAY_PROTECTED_PATHS,
    FilesystemOverlayCandidate,
)


FILESYSTEM_TREE_FORMAT = "securebench.filesystem-tree/v1"
FILESYSTEM_OVERLAY_FORMAT = "securebench.filesystem-overlay/v1"
OVERLAY_CHUNK_BYTES = 4 * 1024 * 1024
MAX_OVERLAY_TREE_ENTRIES = 100_000
MAX_OVERLAY_TREE_BYTES = 8 * 1024 * 1024 * 1024
MAX_OVERLAY_CHANGED_PATHS = 50_000
MAX_OVERLAY_CHANGED_BYTES = 4 * 1024 * 1024 * 1024
MAX_OVERLAY_PATH_BYTES = 4096
MAX_OVERLAY_PATH_DEPTH = 128
MAX_OVERLAY_SYMLINK_TARGET_BYTES = 4096
MAX_OVERLAY_SCAN_SECONDS = 120.0
_READ_BYTES = 1024 * 1024


class OverlayBlobReader(Protocol):
    def read_blob(self, digest: str, *, expected_size: int | None = None) -> bytes:
        ...


@dataclass(frozen=True)
class OverlayScanLimits:
    max_entries: int = MAX_OVERLAY_TREE_ENTRIES
    max_bytes: int = MAX_OVERLAY_TREE_BYTES
    max_seconds: float = MAX_OVERLAY_SCAN_SECONDS
    required_uid: int = 0
    required_gid: int = 0


@dataclass(frozen=True)
class ScannedOverlayNode:
    path: str
    kind: str
    mode: int | None
    size: int
    digest: str | None
    target: str | None
    source: Path
    identity: tuple[int, int, int, int, int, int, int, int]

    def tree_document(self) -> dict[str, Any]:
        if self.kind == "directory":
            return {"path": self.path, "kind": self.kind, "mode": 0o755}
        if self.kind == "regular_file":
            return {
                "path": self.path,
                "kind": self.kind,
                "mode": self.mode,
                "size": self.size,
                "digest": self.digest,
            }
        return {"path": self.path, "kind": self.kind, "target": self.target}


@dataclass(frozen=True)
class ScannedOverlayRoot:
    path: str
    source: Path
    nodes: tuple[ScannedOverlayNode, ...]
    entries: int
    bytes: int
    digest: str
    root_identity: tuple[int, int, int, int, int, int, int, int]


def scan_overlay_root(
    root_path: str,
    source: str | Path,
    *,
    limits: OverlayScanLimits = OverlayScanLimits(),
) -> ScannedOverlayRoot:
    """Scan one stopped root without following links or accepting extra metadata."""
    _validate_absolute_root(root_path)
    _validate_scan_limits(limits)
    host_root = Path(source)
    if not host_root.is_absolute():
        raise CandidateCaptureError("overlay scan source must be absolute")
    try:
        root_info = host_root.lstat()
    except OSError as exc:
        raise CandidateCaptureError("overlay include root is inaccessible") from exc
    if not stat.S_ISDIR(root_info.st_mode) or host_root.is_symlink():
        raise CandidateCaptureError("overlay include root must be a real directory")
    _validate_metadata(host_root, root_info, limits, is_root=True)
    root_device = root_info.st_dev
    deadline = time.monotonic() + limits.max_seconds
    nodes: list[ScannedOverlayNode] = []
    aliases: dict[str, str] = {}
    total_bytes = 0
    pending: list[tuple[Path, PurePosixPath]] = [(host_root, PurePosixPath())]
    while pending:
        _check_deadline(deadline)
        directory, relative_root = pending.pop()
        try:
            children = []
            with os.scandir(directory) as iterator:
                for child in iterator:
                    if len(nodes) + len(children) >= limits.max_entries:
                        raise CandidateCaptureError(
                            "overlay tree exceeds its entry bound"
                        )
                    children.append(child)
                    _check_deadline(deadline)
        except CandidateCaptureError:
            raise
        except OSError as exc:
            raise CandidateCaptureError("overlay tree is inaccessible") from exc
        ordered = sorted(
            children,
            key=lambda entry: entry.name.encode("utf-8", errors="surrogateescape"),
            reverse=True,
        )
        discovered_directories: list[tuple[Path, PurePosixPath]] = []
        for child in ordered:
            _check_deadline(deadline)
            relative = relative_root / child.name
            path = relative.as_posix()
            _validate_relative_path(path)
            alias = portable_path_text(path)
            previous = aliases.get(alias)
            if previous is not None and previous != path:
                raise CandidateCaptureError(
                    f"overlay tree contains portable path aliases: {previous!r} and {path!r}"
                )
            aliases[alias] = path
            source_path = Path(child.path)
            try:
                info = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise CandidateCaptureError(f"overlay path is inaccessible: {path}") from exc
            if info.st_dev != root_device:
                raise CandidateCaptureError(f"overlay tree contains a nested mount: {path}")
            _validate_metadata(source_path, info, limits, is_root=False)
            identity = _identity(info)
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISDIR(info.st_mode):
                node = ScannedOverlayNode(
                    path, "directory", 0o755, 0, None, None, source_path, identity
                )
                discovered_directories.append((source_path, relative))
            elif stat.S_ISREG(info.st_mode):
                if info.st_size < 0 or info.st_size > limits.max_bytes - total_bytes:
                    raise CandidateCaptureError("overlay tree exceeds its byte bound")
                digest = _hash_regular_file(
                    source_path,
                    info,
                    deadline=deadline,
                )
                total_bytes += info.st_size
                node = ScannedOverlayNode(
                    path,
                    "regular_file",
                    _normalized_file_mode(mode),
                    info.st_size,
                    digest,
                    None,
                    source_path,
                    identity,
                )
            elif stat.S_ISLNK(info.st_mode):
                try:
                    target = os.readlink(source_path)
                    encoded_target = target.encode("utf-8", errors="strict")
                except (OSError, UnicodeError) as exc:
                    raise CandidateCaptureError(
                        f"overlay symlink target is invalid: {path}"
                    ) from exc
                if len(encoded_target) > MAX_OVERLAY_SYMLINK_TARGET_BYTES:
                    raise CandidateCaptureError(
                        f"overlay symlink target exceeds its bound: {path}"
                    )
                if len(encoded_target) > limits.max_bytes - total_bytes:
                    raise CandidateCaptureError("overlay tree exceeds its byte bound")
                total_bytes += len(encoded_target)
                node = ScannedOverlayNode(
                    path, "symlink", None, len(encoded_target), None, target, source_path, identity
                )
            else:
                raise CandidateCaptureError(
                    f"overlay tree contains a special file: {path}"
                )
            nodes.append(node)
        pending.extend(discovered_directories)

    nodes.sort(key=lambda node: node.path.encode("utf-8"))
    document = {
        "format": FILESYSTEM_TREE_FORMAT,
        "root": root_path,
        "nodes": [node.tree_document() for node in nodes],
        "entries": len(nodes),
        "bytes": total_bytes,
    }
    return ScannedOverlayRoot(
        path=root_path,
        source=host_root,
        nodes=tuple(nodes),
        entries=len(nodes),
        bytes=total_bytes,
        digest=_digest_bytes(_canonical_json(document)),
        root_identity=_identity(root_info),
    )


def capture_filesystem_overlay(
    baseline_roots: dict[str, str | Path],
    final_roots: dict[str, str | Path],
    spec: FilesystemOverlayCandidate,
    store: CandidateStore,
    *,
    baseline_digest: str,
    scan_limits: OverlayScanLimits = OverlayScanLimits(),
) -> StoredCandidate:
    """Capture a canonical bounded diff between trusted baseline and stopped final roots."""
    expected = tuple(spec.include_roots)
    if set(baseline_roots) != set(expected) or set(final_roots) != set(expected):
        raise CandidateCaptureError("overlay root mapping does not match include_roots")
    baseline = _scan_root_set(expected, baseline_roots, scan_limits, "baseline")
    final = _scan_root_set(expected, final_roots, scan_limits, "final")
    for root in expected:
        if baseline[root].root_identity[5:] != final[root].root_identity[5:]:
            raise CandidateCaptureError("overlay include-root ownership or mode changed")

    change_nodes: list[tuple[str, str, ScannedOverlayNode | None]] = []
    changed_bytes = 0
    for root in sorted(expected, key=lambda value: value.encode("utf-8")):
        baseline_nodes = {node.path: node for node in baseline[root].nodes}
        final_nodes = {node.path: node for node in final[root].nodes}
        _reject_cross_tree_aliases(baseline_nodes, final_nodes)
        for path in sorted(
            set(baseline_nodes) | set(final_nodes),
            key=lambda value: value.encode("utf-8"),
        ):
            before = baseline_nodes.get(path)
            after = final_nodes.get(path)
            if _nodes_equal(before, after):
                continue
            if len(change_nodes) >= spec.max_changed_paths:
                raise CandidateCaptureError("overlay exceeds max_changed_paths")
            if after is not None and after.kind == "symlink":
                if not spec.allow_internal_symlinks:
                    raise CandidateCaptureError(
                        f"overlay contains a changed symlink while disabled: {path}"
                    )
                assert after.target is not None
                _validate_internal_symlink(path, after.target)
            increment = (
                after.size
                if after is not None and after.kind in {"regular_file", "symlink"}
                else 0
            )
            if increment > spec.max_changed_bytes - changed_bytes:
                raise CandidateCaptureError("overlay exceeds max_changed_bytes")
            changed_bytes += increment
            change_nodes.append((root, path, after))

    try:
        with store.transaction() as transaction:
            changes = [
                _stored_change(root, path, node, transaction)
                for root, path, node in change_nodes
            ]
            roots = [
                {
                    "path": root,
                    "baseline_tree_digest": baseline[root].digest,
                    "baseline_entries": baseline[root].entries,
                    "baseline_bytes": baseline[root].bytes,
                    "final_tree_digest": final[root].digest,
                    "final_entries": final[root].entries,
                    "final_bytes": final[root].bytes,
                }
                for root in sorted(expected, key=lambda value: value.encode("utf-8"))
            ]
            payload = {
                "format": FILESYSTEM_OVERLAY_FORMAT,
                "roots": roots,
                "changes": changes,
                "changed_paths": len(changes),
                "changed_bytes": changed_bytes,
            }
            validate_filesystem_overlay_payload(payload)
            return transaction.put_candidate(
                "filesystem_overlay",
                baseline_digest,
                payload,
            )
    except (CandidateStoreCapacityError, CandidateStoreError) as exc:
        raise CandidateCaptureError(
            "filesystem overlay exceeds or corrupts durable storage"
        ) from exc


def _scan_root_set(
    roots: tuple[str, ...],
    sources: dict[str, str | Path],
    limits: OverlayScanLimits,
    label: str,
) -> dict[str, ScannedOverlayRoot]:
    """Apply tree capacities to the whole root set, not once per root."""
    started = time.monotonic()
    result: dict[str, ScannedOverlayRoot] = {}
    entries = 0
    logical_bytes = 0
    for root in roots:
        elapsed = time.monotonic() - started
        remaining_seconds = limits.max_seconds - elapsed
        if remaining_seconds <= 0:
            raise CandidateCaptureError(f"overlay {label} scan exceeded its time bound")
        remaining_entries = limits.max_entries - entries
        remaining_bytes = limits.max_bytes - logical_bytes
        scanned = scan_overlay_root(
            root,
            sources[root],
            limits=OverlayScanLimits(
                max_entries=max(1, remaining_entries),
                max_bytes=max(1, remaining_bytes),
                max_seconds=remaining_seconds,
                required_uid=limits.required_uid,
                required_gid=limits.required_gid,
            ),
        )
        entries += scanned.entries
        logical_bytes += scanned.bytes
        if entries > limits.max_entries or logical_bytes > limits.max_bytes:
            raise CandidateCaptureError(f"overlay {label} tree exceeds framework capacity")
        result[root] = scanned
    return result


def validate_filesystem_overlay_payload(
    payload: dict[str, Any],
    *,
    store: OverlayBlobReader | None = None,
) -> None:
    """Strictly validate a stored overlay manifest and optionally every referenced chunk."""
    if set(payload) != {"format", "roots", "changes", "changed_paths", "changed_bytes"}:
        raise CandidateStoreError("filesystem overlay payload has an invalid shape")
    if payload["format"] != FILESYSTEM_OVERLAY_FORMAT:
        raise CandidateStoreError("filesystem overlay payload has an unsupported format")
    roots = payload["roots"]
    changes = payload["changes"]
    changed_paths = payload["changed_paths"]
    changed_bytes = payload["changed_bytes"]
    if not isinstance(roots, list) or not 1 <= len(roots) <= 16:
        raise CandidateStoreError("filesystem overlay roots are invalid")
    if not isinstance(changes, list):
        raise CandidateStoreError("filesystem overlay changes must be an array")
    _bounded_int(changed_paths, 0, MAX_OVERLAY_CHANGED_PATHS, "changed_paths")
    _bounded_int(changed_bytes, 0, MAX_OVERLAY_CHANGED_BYTES, "changed_bytes")
    if changed_paths != len(changes):
        raise CandidateStoreError("filesystem overlay changed_paths does not match changes")

    root_names: list[str] = []
    root_aliases: set[str] = set()
    for root in roots:
        if not isinstance(root, dict) or set(root) != {
            "path",
            "baseline_tree_digest",
            "baseline_entries",
            "baseline_bytes",
            "final_tree_digest",
            "final_entries",
            "final_bytes",
        }:
            raise CandidateStoreError("filesystem overlay root has an invalid shape")
        path = root["path"]
        try:
            _validate_absolute_root(path)
        except CandidateCaptureError as exc:
            raise CandidateStoreError("filesystem overlay root path is invalid") from exc
        alias = portable_path_text(path)
        if alias in root_aliases:
            raise CandidateStoreError("filesystem overlay roots contain aliases")
        root_aliases.add(alias)
        root_names.append(path)
        _digest_hex(root["baseline_tree_digest"])
        _digest_hex(root["final_tree_digest"])
        _bounded_int(root["baseline_entries"], 0, MAX_OVERLAY_TREE_ENTRIES, "baseline_entries")
        _bounded_int(root["final_entries"], 0, MAX_OVERLAY_TREE_ENTRIES, "final_entries")
        _bounded_int(root["baseline_bytes"], 0, MAX_OVERLAY_TREE_BYTES, "baseline_bytes")
        _bounded_int(root["final_bytes"], 0, MAX_OVERLAY_TREE_BYTES, "final_bytes")
    if root_names != sorted(root_names, key=lambda value: value.encode("utf-8")):
        raise CandidateStoreError("filesystem overlay roots are not canonically sorted")

    known_roots = set(root_names)
    for index, left in enumerate(root_names):
        for right in root_names[index + 1 :]:
            if portable_paths_overlap(left, right):
                raise CandidateStoreError("filesystem overlay roots overlap")
    if sum(root["baseline_entries"] for root in roots) > MAX_OVERLAY_TREE_ENTRIES:
        raise CandidateStoreError("filesystem overlay baseline entries exceed capacity")
    if sum(root["final_entries"] for root in roots) > MAX_OVERLAY_TREE_ENTRIES:
        raise CandidateStoreError("filesystem overlay final entries exceed capacity")
    if sum(root["baseline_bytes"] for root in roots) > MAX_OVERLAY_TREE_BYTES:
        raise CandidateStoreError("filesystem overlay baseline bytes exceed capacity")
    if sum(root["final_bytes"] for root in roots) > MAX_OVERLAY_TREE_BYTES:
        raise CandidateStoreError("filesystem overlay final bytes exceed capacity")
    previous_key: tuple[bytes, bytes] | None = None
    path_aliases: dict[str, set[str]] = {root: set() for root in root_names}
    computed_bytes = 0
    for change in changes:
        if not isinstance(change, dict):
            raise CandidateStoreError("filesystem overlay change must be an object")
        root = change.get("root")
        path = change.get("path")
        kind = change.get("kind")
        if root not in known_roots or not isinstance(path, str):
            raise CandidateStoreError("filesystem overlay change root or path is invalid")
        try:
            _validate_relative_path(path)
        except CandidateCaptureError as exc:
            raise CandidateStoreError("filesystem overlay change path is invalid") from exc
        alias = portable_path_text(path)
        if alias in path_aliases[root]:
            raise CandidateStoreError("filesystem overlay changes contain path aliases")
        path_aliases[root].add(alias)
        key = (root.encode("utf-8"), path.encode("utf-8"))
        if previous_key is not None and key <= previous_key:
            raise CandidateStoreError("filesystem overlay changes are not canonically sorted")
        previous_key = key
        if kind == "absent":
            if set(change) != {"root", "path", "kind"}:
                raise CandidateStoreError("filesystem overlay deletion has an invalid shape")
        elif kind == "directory":
            if set(change) != {"root", "path", "kind", "mode"} or change["mode"] != 0o755:
                raise CandidateStoreError("filesystem overlay directory has invalid metadata")
        elif kind == "symlink":
            if set(change) != {"root", "path", "kind", "target"}:
                raise CandidateStoreError("filesystem overlay symlink has an invalid shape")
            target = change["target"]
            if not isinstance(target, str):
                raise CandidateStoreError("filesystem overlay symlink target is invalid")
            try:
                _validate_internal_symlink(path, target)
                target_bytes = target.encode("utf-8", errors="strict")
            except (CandidateCaptureError, UnicodeError) as exc:
                raise CandidateStoreError("filesystem overlay symlink target is invalid") from exc
            computed_bytes += len(target_bytes)
        elif kind == "regular_file":
            computed_bytes += _validate_stored_file(change, store)
        else:
            raise CandidateStoreError("filesystem overlay change kind is invalid")
        if computed_bytes > MAX_OVERLAY_CHANGED_BYTES:
            raise CandidateStoreError("filesystem overlay changed bytes exceed capacity")
    if computed_bytes != changed_bytes:
        raise CandidateStoreError("filesystem overlay changed_bytes does not match changes")


def _stored_change(
    root: str,
    path: str,
    node: ScannedOverlayNode | None,
    transaction: CandidateStoreTransaction,
) -> dict[str, Any]:
    if node is None:
        return {"root": root, "path": path, "kind": "absent"}
    if node.kind == "directory":
        return {"root": root, "path": path, "kind": "directory", "mode": 0o755}
    if node.kind == "symlink":
        return {"root": root, "path": path, "kind": "symlink", "target": node.target}
    digest = hashlib.sha256()
    chunks: list[dict[str, Any]] = []
    descriptor = _open_regular_file(node.source, node.identity)
    try:
        remaining = node.size
        while remaining:
            content = _read_exact_chunk(descriptor, min(OVERLAY_CHUNK_BYTES, remaining))
            remaining -= len(content)
            digest.update(content)
            chunks.append({"digest": transaction.put_blob(content), "size": len(content)})
        if os.read(descriptor, 1):
            raise CandidateCaptureError(f"overlay file grew during chunking: {node.path}")
    finally:
        os.close(descriptor)
    _require_unchanged(node)
    file_digest = "sha256:" + digest.hexdigest()
    if file_digest != node.digest:
        raise CandidateCaptureError(f"overlay file changed after scanning: {node.path}")
    return {
        "root": root,
        "path": path,
        "kind": "regular_file",
        "mode": node.mode,
        "size": node.size,
        "digest": file_digest,
        "chunks": chunks,
    }


def _validate_stored_file(change: dict[str, Any], store: OverlayBlobReader | None) -> int:
    if set(change) != {"root", "path", "kind", "mode", "size", "digest", "chunks"}:
        raise CandidateStoreError("filesystem overlay file has an invalid shape")
    if change["mode"] not in (0o644, 0o755):
        raise CandidateStoreError("filesystem overlay file mode is invalid")
    size = _bounded_int(change["size"], 0, MAX_OVERLAY_CHANGED_BYTES, "file size")
    expected_digest = change["digest"]
    _digest_hex(expected_digest)
    chunks = change["chunks"]
    if not isinstance(chunks, list):
        raise CandidateStoreError("filesystem overlay file chunks must be an array")
    if size == 0 and chunks:
        raise CandidateStoreError("empty filesystem overlay file has chunks")
    if size > 0 and not chunks:
        raise CandidateStoreError("filesystem overlay file is missing chunks")
    total = 0
    digest = hashlib.sha256()
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict) or set(chunk) != {"digest", "size"}:
            raise CandidateStoreError("filesystem overlay chunk has an invalid shape")
        chunk_digest = chunk["digest"]
        _digest_hex(chunk_digest)
        chunk_size = _bounded_int(chunk["size"], 1, OVERLAY_CHUNK_BYTES, "chunk size")
        if index < len(chunks) - 1 and chunk_size != OVERLAY_CHUNK_BYTES:
            raise CandidateStoreError("filesystem overlay non-final chunk has invalid size")
        total += chunk_size
        if total > size:
            raise CandidateStoreError("filesystem overlay chunks exceed file size")
        if store is not None:
            content = store.read_blob(chunk_digest, expected_size=chunk_size)
            digest.update(content)
    if total != size:
        raise CandidateStoreError("filesystem overlay chunk sizes do not match file size")
    if store is not None and "sha256:" + digest.hexdigest() != expected_digest:
        raise CandidateStoreError("filesystem overlay file digest does not match chunks")
    return size


def _nodes_equal(
    before: ScannedOverlayNode | None,
    after: ScannedOverlayNode | None,
) -> bool:
    if before is None or after is None or before.kind != after.kind:
        return before is after
    if before.kind == "directory":
        return True
    if before.kind == "regular_file":
        return (
            before.mode == after.mode
            and before.size == after.size
            and before.digest == after.digest
        )
    return before.target == after.target


def _reject_cross_tree_aliases(
    baseline: dict[str, ScannedOverlayNode],
    final: dict[str, ScannedOverlayNode],
) -> None:
    aliases: dict[str, str] = {}
    for path in (*baseline, *final):
        alias = portable_path_text(path)
        previous = aliases.get(alias)
        if previous is not None and previous != path:
            raise CandidateCaptureError(
                f"overlay baseline/final paths alias: {previous!r} and {path!r}"
            )
        aliases[alias] = path


def _hash_regular_file(path: Path, before: os.stat_result, *, deadline: float) -> str:
    descriptor = _open_regular_file(path, _identity(before))
    digest = hashlib.sha256()
    read_bytes = 0
    try:
        while read_bytes < before.st_size:
            _check_deadline(deadline)
            chunk = os.read(descriptor, min(_READ_BYTES, before.st_size - read_bytes))
            if not chunk:
                raise CandidateCaptureError("overlay file shrank during scanning")
            read_bytes += len(chunk)
            digest.update(chunk)
        if os.read(descriptor, 1):
            raise CandidateCaptureError("overlay file grew during scanning")
    finally:
        os.close(descriptor)
    after = path.lstat()
    if _identity(after) != _identity(before):
        raise CandidateCaptureError("overlay file changed during scanning")
    return "sha256:" + digest.hexdigest()


def _open_regular_file(path: Path, identity: tuple[int, ...]) -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise CandidateCaptureError("host cannot open overlay files without following links")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
    except OSError as exc:
        raise CandidateCaptureError("overlay regular file cannot be opened safely") from exc
    if not stat.S_ISREG(opened.st_mode) or _identity(opened) != identity:
        os.close(descriptor)
        raise CandidateCaptureError("overlay path changed before reading")
    return descriptor


def _read_exact_chunk(descriptor: int, size: int) -> bytes:
    content = bytearray()
    while len(content) < size:
        chunk = os.read(descriptor, size - len(content))
        if not chunk:
            raise CandidateCaptureError("overlay file shrank during chunking")
        content.extend(chunk)
    return bytes(content)


def _require_unchanged(node: ScannedOverlayNode) -> None:
    try:
        after = node.source.lstat()
    except OSError as exc:
        raise CandidateCaptureError(f"overlay file disappeared: {node.path}") from exc
    if _identity(after) != node.identity:
        raise CandidateCaptureError(f"overlay file changed during capture: {node.path}")


def _validate_metadata(
    path: Path,
    info: os.stat_result,
    limits: OverlayScanLimits,
    *,
    is_root: bool,
) -> None:
    if info.st_uid != limits.required_uid or info.st_gid != limits.required_gid:
        raise CandidateCaptureError("overlay path ownership is unsupported")
    permissions = stat.S_IMODE(info.st_mode)
    if permissions & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX):
        raise CandidateCaptureError("overlay path has unsupported mode metadata")
    if not stat.S_ISDIR(info.st_mode) and info.st_nlink != 1:
        raise CandidateCaptureError("overlay tree contains a hardlink")
    flags = getattr(info, "st_flags", 0)
    if flags:
        raise CandidateCaptureError("overlay path has unsupported filesystem flags")
    if _has_extended_metadata(path):
        raise CandidateCaptureError("overlay tree contains xattrs or ACLs")
    if is_root and not stat.S_ISDIR(info.st_mode):
        raise CandidateCaptureError("overlay include root is not a directory")


def _has_extended_metadata(path: Path) -> bool:
    """Check xattrs without following links, including on minimal Python builds."""
    listxattr = getattr(os, "listxattr", None)
    if listxattr is not None:
        try:
            return bool(listxattr(path, follow_symlinks=False))
        except OSError as exc:
            if exc.errno in {errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}:
                return False
            raise CandidateCaptureError("overlay path metadata cannot be inspected") from exc

    library = ctypes.CDLL(None, use_errno=True)
    encoded = os.fsencode(path)
    if sys.platform == "darwin":
        function = getattr(library, "listxattr", None)
        arguments = (encoded, None, 0, 0x0001)  # XATTR_NOFOLLOW
    else:
        function = getattr(library, "llistxattr", None)
        arguments = (encoded, None, 0)
    if function is None:
        raise CandidateCaptureError("overlay path metadata cannot be inspected")
    function.restype = ctypes.c_ssize_t
    result = function(*arguments)
    if result >= 0:
        return result > 0
    error = ctypes.get_errno()
    if error in {errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}:
        return False
    raise CandidateCaptureError("overlay path metadata cannot be inspected") from OSError(
        error, os.strerror(error)
    )


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_uid,
        info.st_gid,
        stat.S_IMODE(info.st_mode),
    )


def _normalized_file_mode(mode: int) -> int:
    return 0o755 if mode & 0o111 else 0o644


def _validate_scan_limits(limits: OverlayScanLimits) -> None:
    if (
        isinstance(limits.max_entries, bool)
        or not 0 < limits.max_entries <= MAX_OVERLAY_TREE_ENTRIES
        or isinstance(limits.max_bytes, bool)
        or not 0 < limits.max_bytes <= MAX_OVERLAY_TREE_BYTES
        or not isinstance(limits.max_seconds, (int, float))
        or isinstance(limits.max_seconds, bool)
        or not 0 < limits.max_seconds <= MAX_OVERLAY_SCAN_SECONDS
    ):
        raise CandidateCaptureError("overlay scan limits exceed framework capacity")


def _validate_absolute_root(value: str) -> None:
    if not isinstance(value, str):
        raise CandidateCaptureError("overlay root must be text")
    path = PurePosixPath(value)
    if (
        value.startswith("//")
        or not path.is_absolute()
        or str(path) == "/"
        or str(path) != value
        or ".." in path.parts
        or "\\" in value
        or "\x00" in value
    ):
        raise CandidateCaptureError("overlay root must be canonical and absolute")
    if any(
        portable_paths_overlap(path, protected)
        for protected in FILESYSTEM_OVERLAY_PROTECTED_PATHS
    ):
        raise CandidateCaptureError("overlay root overlaps a protected path")


def _validate_relative_path(value: str) -> None:
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        raise CandidateCaptureError("overlay path is not safe POSIX text")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) in ("", ".") or str(path) != value or ".." in path.parts:
        raise CandidateCaptureError("overlay path is not canonical and contained")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise CandidateCaptureError("overlay path is not valid UTF-8") from exc
    if len(encoded) > MAX_OVERLAY_PATH_BYTES or len(path.parts) > MAX_OVERLAY_PATH_DEPTH:
        raise CandidateCaptureError("overlay path exceeds its bounds")


def _validate_internal_symlink(path: str, target: str) -> None:
    if not target:
        raise CandidateCaptureError("overlay symlink target is empty")
    try:
        encoded = target.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise CandidateCaptureError("overlay symlink target is not valid UTF-8") from exc
    if len(encoded) > MAX_OVERLAY_SYMLINK_TARGET_BYTES:
        raise CandidateCaptureError("overlay symlink target exceeds its bound")
    target_path = PurePosixPath(target)
    if target_path.is_absolute() or "\\" in target or "\x00" in target:
        raise CandidateCaptureError("overlay symlink target escapes its include root")
    stack = list(PurePosixPath(path).parent.parts)
    for part in target_path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not stack:
                raise CandidateCaptureError("overlay symlink target escapes its include root")
            stack.pop()
        else:
            stack.append(part)


def _bounded_int(value: Any, minimum: int, maximum: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise CandidateStoreError(f"filesystem overlay {field} is invalid")
    return value


def _digest_hex(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise CandidateStoreError("filesystem overlay digest is invalid")
    return value[7:]


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _check_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise CandidateCaptureError("overlay scan exceeded its time bound")
