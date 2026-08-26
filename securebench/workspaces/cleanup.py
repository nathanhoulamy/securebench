"""Removal of writable filesystem trees after untrusted container use."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path


class WorkspaceCleanupError(RuntimeError):
    """An untrusted writable bind mount could not be removed safely."""


def remove_untrusted_tree(path: str | Path, *, image: str) -> None:
    """Remove a bounded caller-owned tree, restoring hostile permissions if needed."""
    target = Path(path)
    if target.is_symlink():
        raise WorkspaceCleanupError("refusing to remove a symlink as an untrusted tree")
    if not target.exists():
        return
    resolved = target.resolve()
    if resolved == Path(resolved.anchor):
        raise WorkspaceCleanupError("refusing to remove a filesystem root")
    try:
        shutil.rmtree(resolved)
    except PermissionError:
        restore_untrusted_tree_permissions(resolved, image=image)
        try:
            shutil.rmtree(resolved)
        except OSError as exc:
            raise WorkspaceCleanupError("failed to remove untrusted tree after permission repair") from exc


def restore_untrusted_tree_permissions(path: str | Path, *, image: str) -> None:
    """Make a stopped, bounded writable tree traversable by its host owner."""
    target = Path(path)
    if target.is_symlink():
        raise WorkspaceCleanupError("refusing to repair a symlink as an untrusted tree")
    if not target.exists():
        return
    resolved = target.resolve()
    if resolved == Path(resolved.anchor):
        raise WorkspaceCleanupError("refusing to repair permissions on a filesystem root")
    _restore_tree_permissions(resolved, image)


def _restore_tree_permissions(path: Path, image: str) -> None:
    container = f"securebench-cleanup-{uuid.uuid4().hex}"
    command = [
        "docker",
        "run",
        "--name",
        container,
        "--entrypoint",
        "",
        "--user",
        "0:0",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "DAC_OVERRIDE",
        "--cap-add",
        "FOWNER",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        "128m",
        "--pids-limit",
        "32",
        "--mount",
        f"type=bind,source={path},target=/securebench-cleanup",
        image,
        "chmod",
        "-R",
        "a+rwX",
        "--",
        "/securebench-cleanup",
    ]
    failure: WorkspaceCleanupError | None = None
    failure_cause: BaseException | None = None
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode != 0:
            failure = WorkspaceCleanupError("failed to restore untrusted tree permissions")
    except (OSError, subprocess.SubprocessError) as exc:
        failure = WorkspaceCleanupError("failed to run untrusted tree permission repair")
        failure_cause = exc

    try:
        removed = subprocess.run(
            ["docker", "rm", "-f", container],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise WorkspaceCleanupError("failed to remove workspace cleanup container") from exc
    if removed.returncode != 0 and "No such container" not in removed.stderr:
        raise WorkspaceCleanupError("failed to remove workspace cleanup container") from failure
    if failure is not None:
        raise failure from failure_cause
