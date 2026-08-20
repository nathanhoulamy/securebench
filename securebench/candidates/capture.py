"""Safe capture of git-patch and file-bundle candidates."""

from __future__ import annotations

import fnmatch
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Protocol

from securebench.candidates.models import CandidateCaptureError, StoredCandidate
from securebench.candidates.store import CandidateStore
from securebench.candidates.git_repository import (
    GitRepositoryError,
    git_command,
    git_environment,
    run_git_bytes as trusted_run_git_bytes,
    validate_clean_repository,
)
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

    def walk(self, path: str, *, maximum_entries: int) -> Iterable[FilesystemEntry]:
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

    def walk(self, path: str, *, maximum_entries: int) -> Iterable[FilesystemEntry]:
        root = self._host_path(path)
        try:
            root_info = root.lstat()
        except OSError as exc:
            raise CandidateCaptureError(f"candidate tree is inaccessible: {path}") from exc
        if not stat.S_ISDIR(root_info.st_mode):
            raise CandidateCaptureError(f"candidate path is not a directory: {path}")
        entries: list[FilesystemEntry] = []
        pending = [root]
        while pending:
            current = pending.pop()
            directories: list[Path] = []
            try:
                with os.scandir(current) as children:
                    for child_entry in children:
                        if len(entries) >= maximum_entries:
                            raise CandidateCaptureError(
                                f"candidate tree exceeds max_files: {maximum_entries}"
                            )
                        child = Path(child_entry.path)
                        relative = child.relative_to(root).as_posix()
                        _validate_candidate_relative_path(relative)
                        info = child_entry.stat(follow_symlinks=False)
                        entry = _filesystem_entry(relative, info, child)
                        entries.append(entry)
                        if entry.kind == "directory":
                            directories.append(child)
            except CandidateCaptureError:
                raise
            except OSError as exc:
                raise CandidateCaptureError(
                    f"candidate tree is inaccessible below: {path}"
                ) from exc
            pending.extend(
                sorted(
                    directories,
                    key=lambda value: value.relative_to(root).as_posix().encode("utf-8"),
                    reverse=True,
                )
            )
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
    base_commit: str | None = None,
    protected_paths: tuple[str, ...] = (),
) -> StoredCandidate:
    """Validate a binary-capable patch against a clean repository baseline."""
    patch_bytes = patch.encode("utf-8") if isinstance(patch, str) else bytes(patch)
    if len(patch_bytes) > spec.max_patch_bytes:
        raise CandidateCaptureError(
            f"candidate patch exceeds max_patch_bytes: {len(patch_bytes)} > {spec.max_patch_bytes}"
        )
    baseline = Path(baseline_repo).resolve()
    try:
        if base_commit is None:
            base_commit = _run_git_bytes(
                ["rev-parse", "--verify", "HEAD^{commit}"],
                cwd=baseline,
                context="resolve git-patch baseline commit",
            ).decode("ascii").strip()
        validated_commit = validate_clean_repository(baseline, base_commit)
    except (GitRepositoryError, UnicodeError) as exc:
        raise CandidateCaptureError(str(exc)) from exc
    normalized_protected = tuple(_protected_relative_path(value) for value in protected_paths)

    with tempfile.TemporaryDirectory(prefix="securebench-patch-capture-") as temporary_name:
        temporary = Path(temporary_name)
        checkout = temporary / "checkout"
        _run_git(
            ["clone", "--quiet", "--no-hardlinks", "--no-checkout", str(baseline), str(checkout)],
            context="clone git-patch baseline",
        )
        _run_git(
            ["checkout", "--quiet", "--detach", validated_commit],
            cwd=checkout,
            context="checkout baseline",
        )
        patch_path = temporary / "candidate.patch"
        patch_path.write_bytes(patch_bytes)
        if patch_bytes:
            _run_git(
                ["apply", "--binary", "--index", "--whitespace=nowarn", str(patch_path)],
                cwd=checkout,
                context="apply candidate patch",
            )
        names = _run_git_bytes(
            [
                "diff",
                "--cached",
                "--name-only",
                "-z",
                "--no-renames",
                "--diff-filter=ACDMRTUXB",
                "HEAD",
            ],
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
            _validate_patch_path(path, spec, normalized_protected)
            candidate_path = checkout.joinpath(*PurePosixPath(path).parts)
            if candidate_path.is_symlink():
                target = os.readlink(candidate_path)
                _validate_internal_symlink(path, target)
                changed_bytes += len(target.encode("utf-8"))
            elif candidate_path.is_file():
                changed_bytes += candidate_path.stat().st_size
            elif candidate_path.exists():
                raise CandidateCaptureError(f"candidate patch produced unsupported file type: {path}")
        if changed_bytes > spec.max_changed_bytes:
            raise CandidateCaptureError(
                f"candidate patch exceeds max_changed_bytes: {changed_bytes} > {spec.max_changed_bytes}"
            )
        patch_bytes = _canonical_staged_patch(checkout, maximum=spec.max_patch_bytes)

    return store.put_candidate(
        "git_patch",
        baseline_digest,
        {
            "patch_blob": store.put_blob(patch_bytes),
            "patch_bytes": len(patch_bytes),
            "changed_files": list(changed_paths),
            "changed_bytes": changed_bytes,
            "base_commit": validated_commit,
        },
    )


def capture_git_patch_workspace(
    workspace: str | Path,
    baseline_repo: str | Path,
    spec: GitPatchCandidate,
    store: CandidateStore,
    *,
    baseline_digest: str,
    base_commit: str,
    protected_paths: tuple[str, ...] = (),
) -> StoredCandidate:
    """Derive a canonical patch from a stopped workspace using a trusted clone."""
    source = Path(workspace).resolve()
    baseline = Path(baseline_repo).resolve()
    if not source.is_dir() or (source / ".git").is_symlink() or not (source / ".git").is_dir():
        raise CandidateCaptureError("stopped git_patch workspace is not a Git repository")
    try:
        validate_clean_repository(baseline, base_commit)
    except GitRepositoryError as exc:
        raise CandidateCaptureError(str(exc)) from exc
    normalized_protected = tuple(_protected_relative_path(value) for value in protected_paths)
    with tempfile.TemporaryDirectory(prefix="securebench-patch-derive-") as temporary_name:
        checkout = Path(temporary_name) / "checkout"
        _run_git(
            ["clone", "--quiet", "--no-hardlinks", str(baseline), str(checkout)],
            context="clone trusted git-patch baseline",
        )
        _run_git(
            ["checkout", "--quiet", "--detach", base_commit],
            cwd=checkout,
            context="checkout trusted git-patch baseline",
        )
        _synchronize_stopped_worktree(
            source,
            baseline,
            checkout,
            spec,
            protected_paths=normalized_protected,
        )
        _run_git(
            ["add", "--all", "--force", "--", "."],
            cwd=checkout,
            context="stage stopped git-patch workspace",
        )
        patch = _canonical_staged_patch(checkout, maximum=spec.max_patch_bytes)
    return capture_git_patch(
        patch,
        baseline,
        spec,
        store,
        baseline_digest=baseline_digest,
        base_commit=base_commit,
        protected_paths=normalized_protected,
    )


def _capture_tree(
    filesystem: CandidateFilesystem,
    declared: DirectoryTreeEntry,
    store: CandidateStore,
) -> tuple[list[dict[str, object]], int, int]:
    nodes: list[dict[str, object]] = []
    entry_count = 0
    total_bytes = 0
    for info in filesystem.walk(declared.path, maximum_entries=declared.max_files):
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
    try:
        encoded = path.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CandidateCaptureError(f"candidate path is not valid UTF-8: {path!r}") from exc
    if len(encoded) > MAX_CANDIDATE_PATH_BYTES or len(candidate.parts) > MAX_CANDIDATE_PATH_DEPTH:
        raise CandidateCaptureError(f"candidate path exceeds path bounds: {path!r}")


def _validate_internal_symlink(path: str, target: str) -> None:
    try:
        encoded_target = target.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CandidateCaptureError(f"candidate symlink target is not valid UTF-8: {path}") from exc
    if len(encoded_target) > MAX_SYMLINK_TARGET_BYTES:
        raise CandidateCaptureError(f"candidate symlink target is too long: {path}")
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


def _validate_patch_path(
    path: str,
    spec: GitPatchCandidate,
    protected_paths: tuple[str, ...] = (),
) -> None:
    patterns = (*FRAMEWORK_PROTECTED_PATTERNS, *spec.exclude_paths)
    if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns):
        raise CandidateCaptureError(f"candidate patch modifies protected or excluded path: {path}")
    if any(path == value or path.startswith(value + "/") for value in protected_paths):
        raise CandidateCaptureError(f"candidate patch modifies framework-owned path: {path}")
    if spec.allow_paths and not any(fnmatch.fnmatchcase(path, pattern) for pattern in spec.allow_paths):
        raise CandidateCaptureError(f"candidate patch path is outside allow_paths: {path}")


def _protected_relative_path(value: str) -> str:
    _validate_candidate_relative_path(value)
    return str(PurePosixPath(value))


def _is_framework_protected(path: str, protected_paths: tuple[str, ...]) -> bool:
    if any(fnmatch.fnmatchcase(path, pattern) for pattern in FRAMEWORK_PROTECTED_PATTERNS):
        return True
    return any(path == value or path.startswith(value + "/") for value in protected_paths)


def _synchronize_stopped_worktree(
    source: Path,
    baseline: Path,
    checkout: Path,
    spec: GitPatchCandidate,
    *,
    protected_paths: tuple[str, ...],
) -> None:
    baseline_entries = _tree_entry_count(baseline, protected_paths=protected_paths)
    maximum_entries = baseline_entries + max(1024, spec.max_changed_files * 8)
    seen: set[str] = set()
    pending: list[tuple[Path, PurePosixPath]] = [(source, PurePosixPath())]
    visited = 0
    changed_files = 0
    changed_bytes = 0
    while pending:
        current, relative_root = pending.pop()
        try:
            children = sorted(
                os.scandir(current),
                key=lambda item: item.name.encode("utf-8", errors="surrogateescape"),
                reverse=True,
            )
        except OSError as exc:
            raise CandidateCaptureError("stopped git_patch workspace is inaccessible") from exc
        for child in children:
            relative = relative_root / child.name
            path = relative.as_posix()
            _validate_candidate_relative_path(path)
            if path == ".git" or path.startswith(".git/"):
                continue
            if _is_framework_protected(path, protected_paths):
                continue
            visited += 1
            if visited > maximum_entries:
                raise CandidateCaptureError(
                    "stopped git_patch workspace exceeds its traversal bound"
                )
            seen.add(path)
            source_path = Path(child.path)
            target = checkout.joinpath(*relative.parts)
            try:
                info = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise CandidateCaptureError(
                    f"stopped git_patch path is inaccessible: {path}"
                ) from exc
            if stat.S_ISDIR(info.st_mode):
                if target.is_symlink() or (target.exists() and not target.is_dir()):
                    _remove_path(target)
                target.mkdir(parents=True, exist_ok=True)
                pending.append((source_path, relative))
                continue
            if stat.S_ISREG(info.st_mode):
                changed = not _regular_file_equivalent(
                    source_path,
                    info,
                    baseline.joinpath(*relative.parts),
                )
                if changed:
                    changed_files += 1
                    changed_bytes += info.st_size
                    _check_preliminary_patch_bounds(
                        spec,
                        changed_files=changed_files,
                        changed_bytes=changed_bytes,
                    )
                    _remove_path(target)
                    _copy_regular_file(source_path, target, info)
                continue
            if stat.S_ISLNK(info.st_mode):
                target_value = os.readlink(source_path)
                _validate_internal_symlink(path, target_value)
                changed = not _symlink_equivalent(
                    target_value,
                    baseline.joinpath(*relative.parts),
                )
                if changed:
                    changed_files += 1
                    changed_bytes += len(target_value.encode("utf-8"))
                    _check_preliminary_patch_bounds(
                        spec,
                        changed_files=changed_files,
                        changed_bytes=changed_bytes,
                    )
                    _remove_path(target)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.symlink_to(target_value)
                continue
            raise CandidateCaptureError(
                f"stopped git_patch workspace contains unsupported file type: {path}"
            )
    _remove_absent_checkout_paths(checkout, seen, protected_paths=protected_paths)


def _tree_entry_count(root: Path, *, protected_paths: tuple[str, ...]) -> int:
    count = 0
    pending: list[tuple[Path, PurePosixPath]] = [(root, PurePosixPath())]
    while pending:
        current, relative_root = pending.pop()
        try:
            children = tuple(os.scandir(current))
        except OSError as exc:
            raise CandidateCaptureError("git_patch baseline tree is inaccessible") from exc
        for child in children:
            relative = relative_root / child.name
            path = relative.as_posix()
            if path == ".git" or path.startswith(".git/"):
                continue
            if _is_framework_protected(path, protected_paths):
                continue
            count += 1
            try:
                if child.is_dir(follow_symlinks=False):
                    pending.append((Path(child.path), relative))
            except OSError as exc:
                raise CandidateCaptureError("git_patch baseline tree is inaccessible") from exc
    return count


def _regular_file_equivalent(source: Path, source_info: os.stat_result, baseline: Path) -> bool:
    try:
        baseline_info = baseline.lstat()
    except OSError:
        return False
    if not stat.S_ISREG(baseline_info.st_mode):
        return False
    if _normalized_file_mode(source_info.st_mode) != _normalized_file_mode(baseline_info.st_mode):
        return False
    if source_info.st_size != baseline_info.st_size:
        return False
    source_flags = os.O_RDONLY | (os.O_NOFOLLOW if hasattr(os, "O_NOFOLLOW") else 0)
    baseline_flags = os.O_RDONLY | (os.O_NOFOLLOW if hasattr(os, "O_NOFOLLOW") else 0)
    source_descriptor = os.open(source, source_flags)
    baseline_descriptor = os.open(baseline, baseline_flags)
    try:
        while True:
            source_chunk = os.read(source_descriptor, 1024 * 1024)
            baseline_chunk = os.read(baseline_descriptor, 1024 * 1024)
            if source_chunk != baseline_chunk:
                return False
            if not source_chunk:
                return True
    finally:
        os.close(source_descriptor)
        os.close(baseline_descriptor)


def _symlink_equivalent(target: str, baseline: Path) -> bool:
    try:
        return baseline.is_symlink() and os.readlink(baseline) == target
    except OSError:
        return False


def _check_preliminary_patch_bounds(
    spec: GitPatchCandidate,
    *,
    changed_files: int,
    changed_bytes: int,
) -> None:
    if changed_files > spec.max_changed_files:
        raise CandidateCaptureError(
            f"candidate workspace changes too many files: {changed_files} > {spec.max_changed_files}"
        )
    if changed_bytes > spec.max_changed_bytes:
        raise CandidateCaptureError(
            f"candidate workspace exceeds max_changed_bytes: {changed_bytes} > {spec.max_changed_bytes}"
        )


def _copy_regular_file(source: Path, target: Path, before: os.stat_result) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | (os.O_NOFOLLOW if hasattr(os, "O_NOFOLLOW") else 0)
    descriptor = os.open(source, flags)
    try:
        with target.open("wb") as output:
            copied = 0
            while chunk := os.read(descriptor, 1024 * 1024):
                output.write(chunk)
                copied += len(chunk)
        if copied != before.st_size:
            raise CandidateCaptureError("candidate file changed during git_patch capture")
    finally:
        os.close(descriptor)
    after = source.lstat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise CandidateCaptureError("candidate file changed during git_patch capture")
    target.chmod(_normalized_file_mode(before.st_mode))


def _remove_absent_checkout_paths(
    checkout: Path,
    seen: set[str],
    *,
    protected_paths: tuple[str, ...],
) -> None:
    paths = sorted(
        (value for value in checkout.rglob("*") if not value.is_relative_to(checkout / ".git")),
        key=lambda value: len(value.relative_to(checkout).parts),
        reverse=True,
    )
    for target in paths:
        relative = target.relative_to(checkout).as_posix()
        if _is_framework_protected(relative, protected_paths) or relative in seen:
            continue
        _remove_path(target)


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def _canonical_staged_patch(repository: Path, *, maximum: int) -> bytes:
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        completed = subprocess.run(
            git_command(
                [
                    "diff",
                    "--cached",
                    "--binary",
                    "--full-index",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-renames",
                    "HEAD",
                    "--",
                ]
            ),
            cwd=repository,
            env=git_environment(),
            check=False,
            stdout=stdout_file,
            stderr=stderr_file,
        )
        stderr_file.seek(0)
        if completed.returncode != 0:
            error = stderr_file.read(65536).decode("utf-8", errors="replace").strip()
            raise CandidateCaptureError(f"failed to derive canonical candidate patch: {error}")
        size = stdout_file.tell()
        if size > maximum:
            raise CandidateCaptureError(
                f"candidate patch exceeds max_patch_bytes: {size} > {maximum}"
            )
        stdout_file.seek(0)
        return stdout_file.read()


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
    try:
        return trusted_run_git_bytes(arguments, cwd=cwd, context=context)
    except GitRepositoryError as exc:
        raise CandidateCaptureError(str(exc)) from exc
