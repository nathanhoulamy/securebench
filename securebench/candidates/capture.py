"""Safe capture of git-patch and file-bundle candidates."""

from __future__ import annotations

import fnmatch
import os
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Protocol

from securebench.candidates.models import CandidateCaptureError, StoredCandidate
from securebench.candidates.store import CandidateStore
from securebench.schemas.benchmark import (
    DirectoryTreeEntry,
    FileBundleCandidate,
    GitPatchCandidate,
    RegularFileEntry,
)


MAX_CANDIDATE_PATH_BYTES = 4096
MAX_CANDIDATE_PATH_DEPTH = 128
MAX_SYMLINK_TARGET_BYTES = 4096
FRAMEWORK_PROTECTED_PATTERNS = (
    ".git",
    ".git/**",
    ".securebench",
    ".securebench/**",
    "securebench",
    "securebench/**",
)


@dataclass(frozen=True)
class FilesystemEntry:
    path: str
    kind: str
    mode: int
    size: int = 0
    link_target: str | None = None


class CandidateFilesystem(Protocol):
    """Stopped, immutable view of the candidate-producing filesystem."""

    def lstat(self, path: str) -> FilesystemEntry:
        ...

    def read_file(self, path: str, *, maximum: int) -> bytes:
        ...

    def walk(self, path: str) -> Iterable[FilesystemEntry]:
        ...


class HostWorkspaceFilesystem:
    """Candidate filesystem backed by one host directory mounted at guest_root."""

    def __init__(self, root: str | Path, *, guest_root: str) -> None:
        self.root = Path(root).resolve()
        self.guest_root = PurePosixPath(guest_root)
        if not self.guest_root.is_absolute() or ".." in self.guest_root.parts:
            raise CandidateCaptureError("guest_root must be an absolute POSIX path")

    def lstat(self, path: str) -> FilesystemEntry:
        host = self._host_path(path)
        try:
            info = host.lstat()
        except OSError as exc:
            raise CandidateCaptureError(f"candidate path does not exist: {path}") from exc
        return _filesystem_entry(path, info, host)

    def read_file(self, path: str, *, maximum: int) -> bytes:
        host = self._host_path(path)
        before = host.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise CandidateCaptureError(f"candidate path is not a regular file: {path}")
        if before.st_size > maximum:
            raise CandidateCaptureError(
                f"candidate file exceeds bound at {path}: {before.st_size} > {maximum}"
            )
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(host, flags)
        try:
            content = bytearray()
            while len(content) <= maximum:
                chunk = os.read(descriptor, min(1024 * 1024, maximum + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
        finally:
            os.close(descriptor)
        if len(content) > maximum:
            raise CandidateCaptureError(f"candidate file exceeds bound while reading: {path}")
        after = host.lstat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise CandidateCaptureError(f"candidate file changed during capture: {path}")
        return bytes(content)

    def walk(self, path: str) -> Iterable[FilesystemEntry]:
        root = self._host_path(path)
        root_info = root.lstat()
        if not stat.S_ISDIR(root_info.st_mode):
            raise CandidateCaptureError(f"candidate path is not a directory: {path}")
        entries: list[FilesystemEntry] = []
        for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
            directory_names.sort()
            file_names.sort()
            current_path = Path(current)
            for name in tuple(directory_names):
                child = current_path / name
                relative = child.relative_to(root).as_posix()
                child_info = child.lstat()
                entry = _filesystem_entry(relative, child_info, child)
                entries.append(entry)
                if entry.kind == "symlink":
                    directory_names.remove(name)
            for name in file_names:
                child = current_path / name
                relative = child.relative_to(root).as_posix()
                entries.append(_filesystem_entry(relative, child.lstat(), child))
        return tuple(sorted(entries, key=lambda entry: entry.path.encode("utf-8")))

    def _host_path(self, path: str) -> Path:
        guest = PurePosixPath(path)
        if not guest.is_absolute() or not guest.is_relative_to(self.guest_root):
            raise CandidateCaptureError(
                f"candidate path {path!r} is outside captured guest root {str(self.guest_root)!r}"
            )
        relative = guest.relative_to(self.guest_root)
        _validate_candidate_relative_path(relative.as_posix(), allow_empty=True)
        unresolved = self.root.joinpath(*relative.parts)
        parent = unresolved.parent.resolve()
        if not parent.is_relative_to(self.root):
            raise CandidateCaptureError(f"candidate path escapes capture root: {path}")
        return unresolved


def capture_file_bundle(
    filesystem: CandidateFilesystem,
    spec: FileBundleCandidate,
    store: CandidateStore,
    *,
    baseline_digest: str,
) -> StoredCandidate:
    """Capture a bounded file bundle into content-addressed storage."""
    stored_entries: list[dict[str, object]] = []
    aggregate_entries = 0
    aggregate_bytes = 0
    for declared in spec.files:
        if isinstance(declared, RegularFileEntry):
            info = filesystem.lstat(declared.path)
            if info.kind != "regular_file":
                raise CandidateCaptureError(
                    f"candidate entry {declared.id!r} must be a regular file"
                )
            content = filesystem.read_file(declared.path, maximum=declared.max_bytes)
            aggregate_entries += 1
            aggregate_bytes += len(content)
            _check_bundle_aggregate(spec, aggregate_entries, aggregate_bytes)
            stored_entries.append(
                {
                    "id": declared.id,
                    "kind": "regular_file",
                    "source_path": declared.path,
                    "mode": _normalized_file_mode(info.mode),
                    "size": len(content),
                    "blob": store.put_blob(content),
                }
            )
            continue

        tree_nodes, entries, size = _capture_tree(filesystem, declared, store)
        aggregate_entries += entries
        aggregate_bytes += size
        _check_bundle_aggregate(spec, aggregate_entries, aggregate_bytes)
        stored_entries.append(
            {
                "id": declared.id,
                "kind": "directory_tree",
                "source_path": declared.path,
                "nodes": tree_nodes,
            }
        )

    return store.put_candidate(
        "file_bundle",
        baseline_digest,
        {
            "total_entries": aggregate_entries,
            "total_bytes": aggregate_bytes,
            "entries": stored_entries,
        },
    )


def capture_git_patch(
    patch: str | bytes,
    baseline_repo: str | Path,
    spec: GitPatchCandidate,
    store: CandidateStore,
    *,
    baseline_digest: str,
) -> StoredCandidate:
    """Validate a binary-capable patch against a clean repository baseline."""
    patch_bytes = patch.encode("utf-8") if isinstance(patch, str) else bytes(patch)
    if len(patch_bytes) > spec.max_patch_bytes:
        raise CandidateCaptureError(
            f"candidate patch exceeds max_patch_bytes: {len(patch_bytes)} > {spec.max_patch_bytes}"
        )
    baseline = Path(baseline_repo).resolve()
    if not (baseline / ".git").exists():
        raise CandidateCaptureError("git_patch baseline must be a Git repository")

    with tempfile.TemporaryDirectory(prefix="securebench-patch-capture-") as temporary_name:
        temporary = Path(temporary_name)
        checkout = temporary / "checkout"
        _run_git(
            ["clone", "--quiet", "--no-hardlinks", "--no-checkout", str(baseline), str(checkout)],
            context="clone git-patch baseline",
        )
        _run_git(["checkout", "--quiet", "--detach", "HEAD"], cwd=checkout, context="checkout baseline")
        patch_path = temporary / "candidate.patch"
        patch_path.write_bytes(patch_bytes)
        if patch_bytes:
            _run_git(
                ["apply", "--binary", "--index", "--whitespace=nowarn", str(patch_path)],
                cwd=checkout,
                context="apply candidate patch",
            )
        names = _run_git_bytes(
            ["diff", "--cached", "--name-only", "-z", "--diff-filter=ACDMRTUXB", "HEAD"],
            cwd=checkout,
            context="list changed candidate paths",
        )
        changed_paths = tuple(
            part.decode("utf-8", errors="surrogateescape")
            for part in names.split(b"\0")
            if part
        )
        if len(changed_paths) > spec.max_changed_files:
            raise CandidateCaptureError(
                f"candidate patch changes too many files: {len(changed_paths)} > {spec.max_changed_files}"
            )
        changed_bytes = 0
        for path in changed_paths:
            _validate_candidate_relative_path(path)
            _validate_patch_path(path, spec)
            candidate_path = checkout.joinpath(*PurePosixPath(path).parts)
            if candidate_path.is_symlink():
                changed_bytes += len(os.readlink(candidate_path).encode("utf-8"))
            elif candidate_path.is_file():
                changed_bytes += candidate_path.stat().st_size
            elif candidate_path.exists():
                raise CandidateCaptureError(f"candidate patch produced unsupported file type: {path}")
        if changed_bytes > spec.max_changed_bytes:
            raise CandidateCaptureError(
                f"candidate patch exceeds max_changed_bytes: {changed_bytes} > {spec.max_changed_bytes}"
            )

    return store.put_candidate(
        "git_patch",
        baseline_digest,
        {
            "patch_blob": store.put_blob(patch_bytes),
            "patch_bytes": len(patch_bytes),
            "changed_files": list(changed_paths),
            "changed_bytes": changed_bytes,
        },
    )


def _capture_tree(
    filesystem: CandidateFilesystem,
    declared: DirectoryTreeEntry,
    store: CandidateStore,
) -> tuple[list[dict[str, object]], int, int]:
    nodes: list[dict[str, object]] = []
    entry_count = 0
    total_bytes = 0
    for info in filesystem.walk(declared.path):
        _validate_candidate_relative_path(info.path)
        entry_count += 1
        if entry_count > declared.max_files:
            raise CandidateCaptureError(
                f"candidate tree {declared.id!r} exceeds max_files: {entry_count} > {declared.max_files}"
            )
        node: dict[str, object] = {"path": info.path, "kind": info.kind}
        if info.kind == "directory":
            node["mode"] = 0o755
        elif info.kind == "regular_file":
            remaining = declared.max_total_bytes - total_bytes
            content = filesystem.read_file(
                str(PurePosixPath(declared.path) / PurePosixPath(info.path)),
                maximum=max(remaining, 0),
            )
            total_bytes += len(content)
            node.update(
                {
                    "mode": _normalized_file_mode(info.mode),
                    "size": len(content),
                    "blob": store.put_blob(content),
                }
            )
        elif info.kind == "symlink":
            if not declared.allow_internal_symlinks:
                raise CandidateCaptureError(
                    f"candidate tree {declared.id!r} contains a symlink: {info.path}"
                )
            assert info.link_target is not None
            _validate_internal_symlink(info.path, info.link_target)
            target_bytes = info.link_target.encode("utf-8")
            if len(target_bytes) > MAX_SYMLINK_TARGET_BYTES:
                raise CandidateCaptureError(f"candidate symlink target is too long: {info.path}")
            total_bytes += len(target_bytes)
            node["target"] = info.link_target
        else:
            raise CandidateCaptureError(
                f"candidate tree {declared.id!r} contains unsupported file type at {info.path}"
            )
        if total_bytes > declared.max_total_bytes:
            raise CandidateCaptureError(
                f"candidate tree {declared.id!r} exceeds max_total_bytes: "
                f"{total_bytes} > {declared.max_total_bytes}"
            )
        nodes.append(node)
    return nodes, entry_count, total_bytes


def _check_bundle_aggregate(
    spec: FileBundleCandidate,
    entries: int,
    size: int,
) -> None:
    if entries > spec.max_total_files:
        raise CandidateCaptureError(
            f"candidate bundle exceeds max_total_files: {entries} > {spec.max_total_files}"
        )
    if size > spec.max_total_bytes:
        raise CandidateCaptureError(
            f"candidate bundle exceeds max_total_bytes: {size} > {spec.max_total_bytes}"
        )


def _filesystem_entry(path: str, info: os.stat_result, source: Path) -> FilesystemEntry:
    mode = info.st_mode
    if stat.S_ISREG(mode):
        kind = "regular_file"
        target = None
    elif stat.S_ISDIR(mode):
        kind = "directory"
        target = None
    elif stat.S_ISLNK(mode):
        kind = "symlink"
        target = os.readlink(source)
    else:
        kind = "special"
        target = None
    return FilesystemEntry(
        path=path,
        kind=kind,
        mode=stat.S_IMODE(mode),
        size=info.st_size,
        link_target=target,
    )


def _normalized_file_mode(mode: int) -> int:
    return 0o755 if mode & 0o111 else 0o644


def _validate_candidate_relative_path(path: str, *, allow_empty: bool = False) -> None:
    if not isinstance(path, str) or "\\" in path or "\x00" in path:
        raise CandidateCaptureError(f"candidate path is not a safe POSIX path: {path!r}")
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise CandidateCaptureError(f"candidate path is not relative and contained: {path!r}")
    if not allow_empty and str(candidate) in ("", "."):
        raise CandidateCaptureError("candidate path may not be empty")
    encoded = path.encode("utf-8", errors="surrogateescape")
    if len(encoded) > MAX_CANDIDATE_PATH_BYTES or len(candidate.parts) > MAX_CANDIDATE_PATH_DEPTH:
        raise CandidateCaptureError(f"candidate path exceeds path bounds: {path!r}")


def _validate_internal_symlink(path: str, target: str) -> None:
    target_path = PurePosixPath(target)
    if target_path.is_absolute() or "\\" in target or "\x00" in target:
        raise CandidateCaptureError(f"candidate symlink target escapes tree: {path} -> {target}")
    stack = list(PurePosixPath(path).parent.parts)
    for part in target_path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not stack:
                raise CandidateCaptureError(
                    f"candidate symlink target escapes tree: {path} -> {target}"
                )
            stack.pop()
        else:
            stack.append(part)


def _validate_patch_path(path: str, spec: GitPatchCandidate) -> None:
    patterns = (*FRAMEWORK_PROTECTED_PATTERNS, *spec.exclude_paths)
    if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns):
        raise CandidateCaptureError(f"candidate patch modifies protected or excluded path: {path}")
    if spec.allow_paths and not any(fnmatch.fnmatchcase(path, pattern) for pattern in spec.allow_paths):
        raise CandidateCaptureError(f"candidate patch path is outside allow_paths: {path}")


def _run_git(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    context: str,
) -> str:
    return _run_git_bytes(arguments, cwd=cwd, context=context).decode("utf-8", errors="replace")


def _run_git_bytes(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    context: str,
) -> bytes:
    environment = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    completed = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *arguments],
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise CandidateCaptureError(f"failed to {context}: {error}")
    return completed.stdout
