"""Integrity-checked replay of stored candidates."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from securebench.candidates.models import CandidateReplayError, StoredCandidate
from securebench.candidates.store import CandidateStore


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
) -> None:
    """Apply a stored patch to an already reconstructed clean repository."""
    manifest = store.load_candidate(candidate.digest)
    _require_candidate(manifest.type, "git_patch", manifest.baseline_digest, expected_baseline_digest)
    blob = manifest.payload.get("patch_blob")
    size = manifest.payload.get("patch_bytes")
    if not isinstance(blob, str) or not isinstance(size, int):
        raise CandidateReplayError("git_patch candidate payload is invalid")
    patch = store.read_blob(blob, expected_size=size)
    completed = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "apply", "--binary", "--index", "--whitespace=nowarn"],
        cwd=Path(repository),
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        },
        input=patch,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise CandidateReplayError(f"failed to replay git_patch candidate: {error}")


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
    if not isinstance(value, str) or not value or "\\" in value:
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
