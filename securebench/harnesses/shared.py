"""Shared helpers for candidate-producing harnesses."""

from __future__ import annotations

import json
import re
import subprocess
import threading
import uuid
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from securebench.errors import ConfigError
from securebench.progress import emit_progress
from securebench.workspaces.materialization import MaterializationPlan
from securebench.workspaces.path_policy import PathPolicyError, validate_workspace_mount_for_component
from securebench.sandboxes import Sandbox
from securebench.tasks import SecureBenchTask


_IMAGE_BUILD_LOCKS_GUARD = threading.Lock()
_IMAGE_BUILD_LOCKS: dict[str, threading.Lock] = {}


def container_image_for_task(task: SecureBenchTask) -> str:
    return environment_image_for_task(task, context="container harness mode")


def environment_image_for_task(task: SecureBenchTask, *, context: str = "verification") -> str:
    """Return the benchmark environment image selected for task execution."""
    environment = task_environment(task)
    image = environment.get("image") if isinstance(environment, dict) else None
    if not isinstance(image, str) or not image.strip():
        raise ConfigError(
            f"{context} requires benchmark environment.image; "
            "set defaults.environment.image in the manifest or environment.image on the benchmark row"
        )
    return image.strip()


def ensure_environment_image(task: SecureBenchTask) -> bool:
    """Build a missing pack-local task image when a build context is declared."""
    build_context = environment_build_context_for_task(task)
    if build_context is None:
        return False
    image = environment_image_for_task(task, context="local image build")
    lock = _image_build_lock(image)
    with lock:
        inspected = _run_docker_image_command(
            ["docker", "image", "inspect", image],
            action=f"inspect benchmark image {image!r}",
        )
        if inspected.returncode == 0:
            return False

        emit_progress("image_build_start", image=image, context=build_context)
        built = _run_docker_image_command(
            ["docker", "build", "--tag", image, str(build_context)],
            action=f"build benchmark image {image!r}",
        )
        if built.returncode != 0:
            emit_progress(
                "image_build_failed",
                image=image,
                context=build_context,
                exit_code=built.returncode,
                stdout=built.stdout,
                stderr=built.stderr,
            )
            raise ConfigError(
                f"failed to build benchmark image {image!r} from {build_context}: "
                f"{built.stderr.strip()}"
            )
        emit_progress("image_build_done", image=image, context=build_context)
        return True


def environment_build_context_for_task(task: SecureBenchTask) -> Path | None:
    """Resolve an optional pack-relative Docker build context for a task."""
    environment = task_environment(task)
    value = environment.get("build_context")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("benchmark environment.build_context must be a non-empty string")
    relative = Path(value.strip())
    if relative.is_absolute():
        raise ConfigError("benchmark environment.build_context must be pack-relative")

    metadata = task.metadata if isinstance(task.metadata, dict) else {}
    benchmark_pack = metadata.get("benchmark_pack")
    manifest_path = benchmark_pack.get("manifest_path") if isinstance(benchmark_pack, dict) else None
    if not isinstance(manifest_path, str) or not manifest_path:
        raise ConfigError("benchmark environment.build_context requires benchmark pack metadata")
    pack_root = Path(manifest_path).resolve().parent
    unresolved = pack_root / relative
    if unresolved.is_symlink():
        raise ConfigError("benchmark environment.build_context must not be a symlink")
    resolved = unresolved.resolve()
    if not resolved.is_relative_to(pack_root):
        raise ConfigError("benchmark environment.build_context escapes the benchmark pack")
    if not resolved.is_dir():
        raise ConfigError(f"benchmark environment.build_context directory does not exist: {value}")
    if not (resolved / "Dockerfile").is_file():
        raise ConfigError(f"benchmark environment.build_context has no Dockerfile: {value}")
    return resolved


def _image_build_lock(image: str) -> threading.Lock:
    with _IMAGE_BUILD_LOCKS_GUARD:
        return _IMAGE_BUILD_LOCKS.setdefault(image, threading.Lock())


def _run_docker_image_command(
    command: list[str],
    *,
    action: str,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError as exc:
        raise ConfigError(f"failed to {action}: {exc}") from exc


def workspace_mount_target_for_task(task: SecureBenchTask) -> str:
    """Return where the harness workspace should be mounted in the container."""
    environment = task_environment(task)
    workdir = environment.get("workdir")
    if task.task_type == "terminal_task" and isinstance(workdir, str) and workdir.strip():
        return _absolute_container_path(workdir.strip(), "benchmark environment.workdir")
    return "/workspace"


def task_environment(task: SecureBenchTask) -> dict[str, Any]:
    metadata = task.metadata if isinstance(task.metadata, dict) else {}
    environment = metadata.get("environment")
    return environment if isinstance(environment, dict) else {}


def task_workdir(task: SecureBenchTask) -> str | None:
    environment = task_environment(task)
    workdir = environment.get("workdir")
    if isinstance(workdir, str) and workdir.strip():
        return workdir.strip()
    return None


def task_timeout_seconds(task: SecureBenchTask) -> float | None:
    environment = task_environment(task)
    timeout = environment.get("timeout_seconds")
    if timeout is None:
        return None
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ConfigError("benchmark environment.timeout_seconds must be a positive number")
    return float(timeout)


def materialize_workdir_from_image_if_requested(task: SecureBenchTask, destination: Path) -> bool:
    """Copy a task image's workdir into the host workspace for image-backed terminal tasks."""
    environment = task_environment(task)
    requested = environment.get("materialize_workdir_from_image", False)
    if requested is False:
        return False
    if requested is not True:
        raise ConfigError("benchmark environment.materialize_workdir_from_image must be a boolean")
    if task.task_type != "terminal_task":
        raise ConfigError("environment.materialize_workdir_from_image is only supported for terminal_task")

    ensure_environment_image(task)
    image = container_image_for_task(task)
    source = workspace_mount_target_for_task(task)
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
    return True


def run_timeout_seconds(
    task: SecureBenchTask,
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


def workspace_root(task: SecureBenchTask, root: str | Path | None) -> Path | None:
    if root is None:
        return None
    return (Path(root) / workspace_dir_name(task)).resolve()


def workspace_dir_name(task: SecureBenchTask) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", task.id).strip("._")
    if cleaned == task.id and cleaned:
        return cleaned
    digest = sha256(task.id.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned or 'task'}-{digest}"


def agent_task_json(task: SecureBenchTask) -> str:
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
