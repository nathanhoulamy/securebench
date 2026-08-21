"""Integrity-checked replay of stored candidates."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from securebench.candidates.git_repository import (
    GitRepositoryError,
    git_command,
    git_environment,
    run_git_bytes,
    validate_clean_repository,
)
from securebench.candidates.models import CandidateReplayError, StoredCandidate
from securebench.candidates.store import CandidateStore
from securebench.schemas.benchmark import FileBundleCandidate, GitPatchCandidate
from securebench.tasks import BenchmarkTask


def replay_candidate(
    task: BenchmarkTask,
    candidate: StoredCandidate,
    store: CandidateStore,
    root: str | Path,
) -> None:
    """Materialize any currently executable candidate onto its fresh baseline."""
    spec = task.verification.candidate
    if isinstance(spec, FileBundleCandidate):
        replay_file_bundle(
            candidate,
            store,
            root,
            guest_root=task.environment.workdir,
            expected_baseline_digest=task.baseline_digest,
        )
        return
    if isinstance(spec, GitPatchCandidate):
        base_commit = task.input.get("base_commit")
        if not isinstance(base_commit, str):
            raise CandidateReplayError("repo_patch task has no canonical base_commit")
        replay_git_patch(
            candidate,
            store,
            root,
            expected_baseline_digest=task.baseline_digest,
            expected_base_commit=base_commit,
        )
        return
    raise CandidateReplayError(f"candidate replay is not implemented for {spec.type!r}")


def replay_file_bundle(
    candidate: StoredCandidate,
    store: CandidateStore,
    root: str | Path,
    *,
    guest_root: str,
    expected_baseline_digest: str,
) -> None:
    """Materialize a file bundle into a clean host-backed guest root."""
    manifest = store.load_candidate(candidate.digest)
    _require_candidate(manifest.type, "file_bundle", manifest.baseline_digest, expected_baseline_digest)
    payload = manifest.payload
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise CandidateReplayError("file_bundle candidate entries are invalid")
    host_root = Path(root).resolve()
    guest = PurePosixPath(guest_root)
    if not guest.is_absolute():
        raise CandidateReplayError("file_bundle replay guest_root must be absolute")
    for entry in entries:
        if not isinstance(entry, dict):
            raise CandidateReplayError("file_bundle candidate entry is invalid")
        source_path = entry.get("source_path")
        if not isinstance(source_path, str):
            raise CandidateReplayError("file_bundle candidate source_path is invalid")
        target = _guest_to_host(host_root, guest, source_path)
        kind = entry.get("kind")
        if kind == "regular_file":
            _remove_regular_target(target)
            _write_blob(target, entry, store)
        elif kind == "directory_tree":
            _remove_tree_target(target)
            target.mkdir(parents=True, exist_ok=True)
            nodes = entry.get("nodes")
            if not isinstance(nodes, list):
                raise CandidateReplayError("directory_tree nodes are invalid")
            _replay_tree(target, nodes, store)
        else:
            raise CandidateReplayError(f"unsupported file_bundle entry kind: {kind!r}")


def replay_git_patch(
    candidate: StoredCandidate,
    store: CandidateStore,
    repository: str | Path,
    *,
    expected_baseline_digest: str,
    expected_base_commit: str | None = None,
) -> None:
    """Apply a stored patch to an already reconstructed clean repository."""
    manifest = store.load_candidate(candidate.digest)
    _require_candidate(manifest.type, "git_patch", manifest.baseline_digest, expected_baseline_digest)
    blob = manifest.payload.get("patch_blob")
    size = manifest.payload.get("patch_bytes")
    base_commit = manifest.payload.get("base_commit")
    changed_files = manifest.payload.get("changed_files")
    changed_bytes = manifest.payload.get("changed_bytes")
    if (
        not isinstance(blob, str)
        or not isinstance(size, int)
        or not isinstance(base_commit, str)
        or not isinstance(changed_files, list)
        or not all(isinstance(path, str) for path in changed_files)
        or not isinstance(changed_bytes, int)
    ):
        raise CandidateReplayError("git_patch candidate payload is invalid")
    if expected_base_commit is not None and base_commit != expected_base_commit:
        raise CandidateReplayError("git_patch candidate base_commit does not match the task")
    try:
        validate_clean_repository(repository, base_commit)
    except GitRepositoryError as exc:
        raise CandidateReplayError(str(exc)) from exc
    patch = store.read_blob(blob, expected_size=size)
    if patch:
        completed = subprocess.run(
            git_command(["apply", "--binary", "--index", "--whitespace=nowarn"]),
            cwd=Path(repository),
            env=git_environment(),
            input=patch,
            check=False,
            capture_output=True,
        )
        if completed.returncode != 0:
            error = completed.stderr[:65536].decode("utf-8", errors="replace").strip()
            raise CandidateReplayError(f"failed to replay git_patch candidate: {error}")
    try:
        replayed_patch = run_git_bytes(
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
            ],
            cwd=Path(repository),
            context="verify replayed git_patch bytes",
        )
        names = run_git_bytes(
            [
                "diff",
                "--cached",
                "--name-only",
                "-z",
                "--no-renames",
                "--diff-filter=ACDMRTUXB",
                "HEAD",
            ],
            cwd=Path(repository),
            context="verify replayed git_patch paths",
        )
    except GitRepositoryError as exc:
        raise CandidateReplayError(str(exc)) from exc
    replayed_paths = [
        part.decode("utf-8", errors="surrogateescape") for part in names.split(b"\0") if part
    ]
    if replayed_patch != patch or replayed_paths != changed_files:
        raise CandidateReplayError("replayed git_patch does not match its stored manifest")
    actual_bytes = 0
    root = Path(repository).resolve()
    for path in replayed_paths:
        relative = _safe_relative_path(path)
        target = root.joinpath(*relative.parts)
        if target.is_symlink():
            link_target = os.readlink(target)
            _validate_replayed_symlink(path, link_target)
            actual_bytes += len(link_target.encode("utf-8"))
        elif target.is_file():
            actual_bytes += target.stat().st_size
        elif target.exists():
            raise CandidateReplayError("replayed git_patch produced an unsupported file type")
    if actual_bytes != changed_bytes:
        raise CandidateReplayError("replayed git_patch byte count does not match its manifest")


def _validate_replayed_symlink(path: str, target: str) -> None:
    try:
        target_bytes = target.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CandidateReplayError(f"replayed symlink target is not valid UTF-8: {path}") from exc
    if len(target_bytes) > 4096:
        raise CandidateReplayError(f"replayed symlink target is too long: {path}")
    target_path = PurePosixPath(target)
    if target_path.is_absolute() or "\\" in target or "\x00" in target:
        raise CandidateReplayError(f"replayed symlink escapes repository: {path}")
    stack = list(PurePosixPath(path).parent.parts)
    for part in target_path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not stack:
                raise CandidateReplayError(f"replayed symlink escapes repository: {path}")
            stack.pop()
        else:
            stack.append(part)


def _replay_tree(root: Path, nodes: list[Any], store: CandidateStore) -> None:
    directories: list[tuple[Path, int]] = []
    symlinks: list[tuple[Path, str]] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise CandidateReplayError("directory_tree node is invalid")
        relative = _safe_relative_path(node.get("path"))
        target = root.joinpath(*relative.parts)
        if not target.parent.resolve().is_relative_to(root.resolve()):
            raise CandidateReplayError("directory_tree target escapes replay root")
        kind = node.get("kind")
        if kind == "directory":
            target.mkdir(parents=True, exist_ok=True)
            directories.append((target, _mode(node)))
        elif kind == "regular_file":
            _remove_regular_target(target)
            _write_blob(target, node, store)
        elif kind == "symlink":
            link_target = node.get("target")
            if not isinstance(link_target, str):
                raise CandidateReplayError("directory_tree symlink target is invalid")
            symlinks.append((target, link_target))
        else:
            raise CandidateReplayError(f"unsupported directory_tree node kind: {kind!r}")
    for target, link_target in symlinks:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            raise CandidateReplayError(f"candidate replay target already exists: {target}")
        target.symlink_to(link_target)
    for target, mode in reversed(directories):
        target.chmod(mode)


def _write_blob(target: Path, value: dict[str, Any], store: CandidateStore) -> None:
    blob = value.get("blob")
    size = value.get("size")
    if not isinstance(blob, str) or not isinstance(size, int) or size < 0:
        raise CandidateReplayError("candidate file blob metadata is invalid")
    if target.exists() or target.is_symlink():
        raise CandidateReplayError(f"candidate replay target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(store.read_blob(blob, expected_size=size))
    target.chmod(_mode(value))


def _remove_regular_target(target: Path) -> None:
    if target.is_symlink():
        raise CandidateReplayError(f"candidate replay target is a baseline symlink: {target}")
    if not target.exists():
        return
    if not target.is_file():
        raise CandidateReplayError(f"candidate regular-file target has incompatible type: {target}")
    target.unlink()


def _remove_tree_target(target: Path) -> None:
    if target.is_symlink():
        raise CandidateReplayError(f"candidate tree target is a baseline symlink: {target}")
    if not target.exists():
        return
    if not target.is_dir():
        raise CandidateReplayError(f"candidate tree target has incompatible type: {target}")
    shutil.rmtree(target)


def _guest_to_host(root: Path, guest_root: PurePosixPath, path: str) -> Path:
    guest = PurePosixPath(path)
    if not guest.is_absolute() or not guest.is_relative_to(guest_root) or ".." in guest.parts:
        raise CandidateReplayError(f"candidate path is outside replay guest root: {path!r}")
    relative = guest.relative_to(guest_root)
    target = root.joinpath(*relative.parts)
    if not target.parent.resolve().is_relative_to(root):
        raise CandidateReplayError(f"candidate path escapes replay root: {path!r}")
    return target


def _safe_relative_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise CandidateReplayError("candidate tree path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) in ("", "."):
        raise CandidateReplayError("candidate tree path is unsafe")
    return path


def _mode(value: dict[str, Any]) -> int:
    mode = value.get("mode")
    if mode not in {0o644, 0o755}:
        raise CandidateReplayError(f"candidate file mode is invalid: {mode!r}")
    return mode


def _require_candidate(
    actual_type: str,
    expected_type: str,
    actual_baseline: str,
    expected_baseline: str,
) -> None:
    if actual_type != expected_type:
        raise CandidateReplayError(
            f"stored candidate type {actual_type!r} cannot be replayed as {expected_type!r}"
        )
    if actual_baseline != expected_baseline:
        raise CandidateReplayError(
            f"candidate baseline mismatch: expected {expected_baseline}, got {actual_baseline}"
        )
