"""Shared helpers for candidate-producing harnesses."""

from __future__ import annotations

import json
import re
import subprocess
import uuid
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from securebench.errors import ConfigError
from securebench.workspaces.materialization import MaterializationPlan
from securebench.workspaces.path_policy import PathPolicyError, validate_workspace_mount_for_component
from securebench.sandboxes import Sandbox
from securebench.tasks import BenchmarkTask


def container_image_for_task(task: BenchmarkTask) -> str:
    return environment_image_for_task(task)


def environment_image_for_task(task: BenchmarkTask) -> str:
    """Return the benchmark environment image selected for task execution."""
    return task.environment.image


def workspace_mount_target_for_task(task: BenchmarkTask) -> str:
    """Return where the harness workspace should be mounted in the container."""
    return _absolute_container_path(task.environment.workdir, "benchmark environment.workdir")


def task_workdir(task: BenchmarkTask) -> str:
    return task.environment.workdir


def task_timeout_seconds(task: BenchmarkTask) -> float:
    return float(task.environment.timeout_seconds)


def task_allowed_domains(task: BenchmarkTask, configured: tuple[str, ...]) -> tuple[str, ...]:
    """Apply the row's solving-phase network ceiling to tester egress."""
    if task.environment.agent_network == "none":
        return ()
    return configured


def materialize_image_workdir(task: BenchmarkTask, destination: Path) -> None:
    """Create the candidate-visible baseline from the immutable image workdir."""
    image = container_image_for_task(task)
    source = task.environment.workdir
    destination.mkdir(parents=True, exist_ok=True)
    container = f"securebench-copy-{uuid.uuid4().hex}"
    created = subprocess.run(
        ["docker", "create", "--name", container, image],
        check=False,
        capture_output=True,
        text=True,
    )
    if created.returncode != 0:
        raise ConfigError(
            "failed to create image materialization container "
            f"for {image!r}: {created.stderr.strip()}"
        )
    try:
        copied = subprocess.run(
            ["docker", "cp", f"{container}:{source}/.", str(destination)],
            check=False,
            capture_output=True,
            text=True,
        )
        if copied.returncode != 0:
            raise ConfigError(
                "failed to materialize benchmark image workdir "
                f"{source!r} from {image!r}: {copied.stderr.strip()}"
            )
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container],
            check=False,
            capture_output=True,
            text=True,
        )


def run_timeout_seconds(
    task: BenchmarkTask,
    *,
    context_timeout: Any = None,
    fallback_timeout: float | None = None,
) -> float | None:
    if context_timeout is not None:
        return optional_positive_number(context_timeout, "timeout")
    return task_timeout_seconds(task) or fallback_timeout


def workspace_path(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty workspace-relative path")
    try:
        return validate_workspace_mount_for_component("agent", value).path
    except PathPolicyError as exc:
        raise ConfigError(f"{field} is unsafe: {exc}") from exc


def container_workspace_path(path: str, *, mount_target: str = "/workspace") -> str:
    """Return a path to the harness workspace inside the benchmark container."""
    candidate = PurePosixPath(path)
    if candidate.is_absolute():
        return str(candidate)
    return str(PurePosixPath(mount_target) / candidate)


def optional_positive_number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{field} must be a positive number")
    return float(value)


def reject_unknown_fields(
    data: dict[str, Any], allowed: set[str], section: str
) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"{section} contains unsupported field(s): {', '.join(unknown)}")


def workspace_root(task: BenchmarkTask, root: str | Path | None) -> Path | None:
    if root is None:
        return None
    return (Path(root) / workspace_dir_name(task)).resolve()


def workspace_dir_name(task: BenchmarkTask) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", task.id).strip("._")
    if cleaned == task.id and cleaned:
        return cleaned
    digest = sha256(task.id.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned or 'task'}-{digest}"


def agent_task_json(task: BenchmarkTask) -> str:
    return json.dumps(task.agent_payload(), indent=2, sort_keys=True) + "\n"


def reject_task_file_collision(task_file: str, plan: MaterializationPlan) -> None:
    path = PurePosixPath(task_file)
    for resource in plan.resources:
        if paths_overlap(path, PurePosixPath(resource.relative_path)):
            raise ConfigError(
                f"harness.config.task_file collides with public materialized path: {task_file}"
            )


def paths_overlap(left: PurePosixPath, right: PurePosixPath) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def close_sandbox(sandbox: Sandbox) -> None:
    close = getattr(sandbox, "close", None)
    if callable(close):
        close()


def _absolute_container_path(value: str, field: str) -> str:
    if "\\" in value:
        raise ConfigError(f"{field} may not contain backslashes")
    path = PurePosixPath(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ConfigError(f"{field} must be an absolute container path without '..'")
    return str(path)
