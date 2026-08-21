"""Docker CLI sandbox implementation."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from securebench.path_safety import portable_paths_overlap
from securebench.progress import emit_progress, wants_agent_output
from securebench.sandboxes.base import (
    CommandResult,
    Sandbox,
    resolve_sandbox_host_path,
    run_bounded_subprocess,
    timeout_command_result,
    timeout_output,
)

DOCKER_MEM_LIMIT_ENV = "SECUREBENCH_DOCKER_MEM_LIMIT"
DOCKER_PIDS_LIMIT_ENV = "SECUREBENCH_DOCKER_PIDS_LIMIT"
DOCKER_TMPFS_ENV = "SECUREBENCH_DOCKER_TMPFS"
DOCKER_OPERATION_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class DockerBindMount:
    """Extra Docker bind mount for a workspace path."""

    source: str | Path
    target: str
    read_only: bool = True


@dataclass(frozen=True)
class DockerVolumeMount:
    """Named Docker volume mounted from one pre-existing volume subdirectory."""

    source: str
    target: str
    subpath: str
    read_only: bool = False


class DockerSandboxError(RuntimeError):
    """Docker could not establish or clean up the trusted sandbox boundary."""


def validate_docker_bind_mounts(
    mounts: tuple[DockerBindMount, ...],
    *,
    workspace_mount_target: str,
) -> None:
    """Validate bind sources, targets, and overlap without starting Docker."""
    _docker_bind_mount_args(mounts, workspace_mount_target=workspace_mount_target)


class DockerSandbox(Sandbox):
    """Run commands in a Docker-backed workspace."""

    def __init__(
        self,
        *,
        image: str = "python:3.11-slim",
        root: str | Path | None = None,
        env_names: tuple[str, ...] = (),
        env: dict[str, str] | None = None,
        persistent: bool = True,
        network: str = "none",
        cap_drop: tuple[str, ...] = ("ALL",),
        cap_add: tuple[str, ...] = (),
        read_only: bool = True,
        tmpfs: tuple[str, ...] = ("/tmp",),
        mem_limit: str | None = "1g",
        pids_limit: int | None = 256,
        security_opt: tuple[str, ...] = ("no-new-privileges:true",),
        mounts: tuple[DockerBindMount, ...] = (),
        volume_mounts: tuple[DockerVolumeMount, ...] = (),
        workspace_mount_target: str = "/workspace",
        workspace_read_only: bool = False,
        allow_resource_overrides: bool = True,
    ) -> None:
        self.image = image
        self.env_names = tuple(env_names)
        self.env = {} if env is None else dict(env)
        self.persistent = persistent
        self.network = network
        self.cap_drop = tuple(cap_drop)
        self.cap_add = tuple(cap_add)
        self.read_only = read_only
        if not isinstance(allow_resource_overrides, bool):
            raise ValueError("Docker allow_resource_overrides must be a boolean")
        self.tmpfs = _docker_tmpfs_override(tmpfs) if allow_resource_overrides else tuple(tmpfs)
        self.mem_limit = (
            _docker_mem_limit_override(mem_limit) if allow_resource_overrides else mem_limit
        )
        self.pids_limit = (
            _docker_pids_limit_override(pids_limit) if allow_resource_overrides else pids_limit
        )
        self.security_opt = tuple(security_opt)
        self.mounts = tuple(mounts)
        self.volume_mounts = tuple(volume_mounts)
        if not isinstance(workspace_read_only, bool):
            raise ValueError("Docker workspace_read_only must be a boolean")
        self.workspace_read_only = workspace_read_only
        self.workspace_mount_target = _docker_bind_mount_target(workspace_mount_target, allow_workspace_root=True)
        self._container_name: str | None = None
        self._owns_root = root is None
        self.root = (
            Path(root)
            if root is not None
            else Path(tempfile.mkdtemp(prefix="securebench-"))
        ).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        emit_progress(
            "sandbox_create",
            kind="docker",
            image=self.image,
            root=self.root,
            network=self.network,
            read_only=self.read_only,
        )

    def run(
        self,
        command: str | list[str] | tuple[str, ...],
        *,
        workdir: str | None = None,
        timeout: float | None = None,
        stdin: str | bytes | None = None,
    ) -> CommandResult:
        normalized = _normalize_command(command)
        docker_workdir = _docker_path(workdir or ".", workspace_mount_target=self.workspace_mount_target)
        emit_progress(
            "sandbox_command",
            kind="docker",
            image=self.image,
            workdir=docker_workdir,
            command=" ".join(normalized),
        )
        if self.persistent:
            self._ensure_container()
            command_container_name = None
            docker_command = [
                "docker",
                "exec",
                *(("-i",) if stdin is not None else ()),
                "-w",
                docker_workdir,
                self._container_name or "",
                *normalized,
            ]
        else:
            command_container_name = f"securebench-{uuid.uuid4().hex}"
            docker_command = [
                "docker",
                "run",
                "--rm",
                "--name",
                command_container_name,
                "--entrypoint",
                "",
                *(("-i",) if stdin is not None else ()),
                *_docker_workspace_mount_args(
                    self.root,
                    self.workspace_mount_target,
                    read_only=self.workspace_read_only,
                ),
                *_docker_bind_mount_args(self.mounts, workspace_mount_target=self.workspace_mount_target),
                *_docker_volume_mount_args(self.volume_mounts),
                "-w",
                docker_workdir,
                *_docker_hardening_args(
                    network=self.network,
                    cap_drop=self.cap_drop,
                    cap_add=self.cap_add,
                    read_only=self.read_only,
                    tmpfs=self.tmpfs,
                    mem_limit=self.mem_limit,
                    pids_limit=self.pids_limit,
                    security_opt=self.security_opt,
                ),
                *_docker_env_args(self.env_names),
                *_docker_explicit_env_args(self.env),
                self.image,
                *normalized,
            ]
        try:
            stream_agent_output = _is_codex_agent_command(normalized) and wants_agent_output()
            if stream_agent_output:
                if stdin is not None:
                    raise ValueError("Streaming agent commands do not support stdin")
            output_emitter = _AgentOutputEmitter() if stream_agent_output else None
            completed = run_bounded_subprocess(
                docker_command,
                timeout=timeout,
                stdin=stdin,
                on_output=None if output_emitter is None else output_emitter.feed,
            )
            if output_emitter is not None:
                output_emitter.flush()
        except subprocess.TimeoutExpired as exc:
            if self.persistent:
                self.close()
            elif command_container_name is not None:
                _remove_named_container(command_container_name)
            result = timeout_command_result(
                normalized,
                timeout,
                stdout=exc.stdout,
                stderr=exc.stderr,
                stdout_bytes=getattr(exc, "stdout_bytes", None),
                stderr_bytes=getattr(exc, "stderr_bytes", None),
                stdout_truncated=getattr(exc, "stdout_truncated", False),
                stderr_truncated=getattr(exc, "stderr_truncated", False),
                stdout_valid_utf8=getattr(exc, "stdout_valid_utf8", True),
                stderr_valid_utf8=getattr(exc, "stderr_valid_utf8", True),
            )
            emit_progress(
                "sandbox_result",
                kind="docker",
                exit_code=result.exit_code,
                command=" ".join(normalized),
                stdout=result.stdout,
                stderr=result.stderr,
            )
            return result
        stdout = timeout_output(completed.stdout)
        stderr = timeout_output(completed.stderr)
        emit_progress(
            "sandbox_result",
            kind="docker",
            exit_code=completed.returncode,
            command=" ".join(normalized),
            stdout=stdout,
            stderr=stderr,
        )
        return CommandResult(
            command=normalized,
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            stdout_bytes=getattr(completed, "stdout_bytes", len(stdout.encode("utf-8"))),
            stderr_bytes=getattr(completed, "stderr_bytes", len(stderr.encode("utf-8"))),
            stdout_truncated=getattr(completed, "stdout_truncated", False),
            stderr_truncated=getattr(completed, "stderr_truncated", False),
            stdout_valid_utf8=getattr(completed, "stdout_valid_utf8", True),
            stderr_valid_utf8=getattr(completed, "stderr_valid_utf8", True),
        )

    def close(self) -> None:
        """Remove the persistent container and any sandbox-owned writable root."""
        if self._container_name is not None:
            name = self._container_name
            _remove_named_container(name)
            self._container_name = None
        if self._owns_root:
            from securebench.workspaces.cleanup import remove_untrusted_tree

            try:
                remove_untrusted_tree(self.root, image=self.image)
            except Exception as exc:
                raise DockerSandboxError("failed to remove Docker sandbox workspace") from exc
            self._owns_root = False

    def __enter__(self) -> "DockerSandbox":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def write_file(self, path: str | PurePosixPath, content: str | bytes) -> None:
        target = self._host_path(path, for_write=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)

    def read_file(self, path: str | PurePosixPath) -> str:
        return self._host_path(path).read_text()

    def extract_file(self, path: str | PurePosixPath) -> bytes:
        return self._host_path(path).read_bytes()

    def _host_path(self, path: str | PurePosixPath, *, for_write: bool = False) -> Path:
        return resolve_sandbox_host_path(self.root, path, for_write=for_write)

    def _ensure_container(self) -> None:
        if self._container_name is not None:
            return
        # Validate all mount inputs before assigning a container identity so a
        # rejected mount plan cannot trigger cleanup for a container that was
        # never started.
        _docker_bind_mount_args(
            self.mounts,
            workspace_mount_target=self.workspace_mount_target,
        )
        _docker_volume_mount_args(self.volume_mounts)
        self._container_name = f"securebench-{uuid.uuid4().hex}"
        emit_progress(
            "sandbox_start",
            kind="docker",
            image=self.image,
            container=self._container_name,
        )
        try:
            completed = subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    self._container_name,
                    "--entrypoint",
                    "",
                    *_docker_workspace_mount_args(
                        self.root,
                        self.workspace_mount_target,
                        read_only=self.workspace_read_only,
                    ),
                    *_docker_bind_mount_args(
                        self.mounts,
                        workspace_mount_target=self.workspace_mount_target,
                    ),
                    *_docker_volume_mount_args(self.volume_mounts),
                    "-w",
                    self.workspace_mount_target,
                    *_docker_hardening_args(
                        network=self.network,
                        cap_drop=self.cap_drop,
                        cap_add=self.cap_add,
                        read_only=self.read_only,
                        tmpfs=self.tmpfs,
                        mem_limit=self.mem_limit,
                        pids_limit=self.pids_limit,
                        security_opt=self.security_opt,
                    ),
                    *_docker_env_args(self.env_names),
                    *_docker_explicit_env_args(self.env),
                    self.image,
                    "sleep",
                    "infinity",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=DOCKER_OPERATION_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            try:
                self.close()
            except DockerSandboxError as cleanup_error:
                raise DockerSandboxError(
                    "failed to start and remove Docker sandbox container"
                ) from cleanup_error
            raise DockerSandboxError("failed to start Docker sandbox container") from exc
        if completed.returncode != 0:
            try:
                self.close()
            except DockerSandboxError as cleanup_error:
                raise DockerSandboxError(
                    "failed to start and remove Docker sandbox container"
                ) from cleanup_error
            raise DockerSandboxError("failed to start Docker sandbox container")


def _normalize_command(command: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(command, str):
        return ("sh", "-lc", command)
    if not command:
        raise ValueError("Command must not be empty")
    return tuple(str(part) for part in command)


def _is_codex_agent_command(command: tuple[str, ...]) -> bool:
    return "codex exec" in " ".join(command)


class _AgentOutputEmitter:
    def __init__(self) -> None:
        self.buffers = {"stdout": "", "stderr": ""}

    def feed(self, stream: str, content: str) -> None:
        buffer = self.buffers[stream] + content
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            emit_progress("agent_output", stream=stream, line=line)
        self.buffers[stream] = buffer

    def flush(self) -> None:
        for stream, content in self.buffers.items():
            if content:
                emit_progress("agent_output", stream=stream, line=content)
                self.buffers[stream] = ""


def _remove_named_container(name: str) -> None:
    try:
        completed = subprocess.run(
            ["docker", "rm", "-f", name],
            check=False,
            capture_output=True,
            text=True,
            timeout=DOCKER_OPERATION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DockerSandboxError(
            f"failed to remove Docker sandbox container {name!r}"
        ) from exc
    if completed.returncode != 0 and "no such container" not in completed.stderr.lower():
        raise DockerSandboxError(f"failed to remove Docker sandbox container {name!r}")


def _docker_path(path: str, *, workspace_mount_target: str = "/workspace") -> str:
    if path.startswith("/workspace"):
        return path
    relative = PurePosixPath(path)
    if relative.is_absolute():
        return str(relative)
    return str(PurePosixPath(workspace_mount_target) / relative)


def _docker_workspace_mount_args(
    root: Path,
    target: str,
    *,
    read_only: bool,
) -> tuple[str, str]:
    option = f"{root}:{target}"
    if read_only:
        option += ":ro"
    return "-v", option


def _docker_env_args(env_names: tuple[str, ...]) -> tuple[str, ...]:
    args: list[str] = []
    for name in env_names:
        if not isinstance(name, str) or not name or "=" in name or "\x00" in name:
            raise ValueError(f"Docker environment variable name is invalid: {name!r}")
        args.extend(["-e", name])
    return tuple(args)


def _docker_explicit_env_args(env: dict[str, str]) -> tuple[str, ...]:
    args: list[str] = []
    for name, value in env.items():
        if (
            not isinstance(name, str)
            or not name
            or "=" in name
            or "\x00" in name
        ):
            raise ValueError(f"Docker environment variable name is invalid: {name!r}")
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError(f"Docker environment variable value is invalid for {name!r}")
        args.extend(["-e", f"{name}={value}"])
    return tuple(args)


def _docker_bind_mount_args(
    mounts: tuple[DockerBindMount, ...],
    *,
    workspace_mount_target: str = "/workspace",
) -> tuple[str, ...]:
    args: list[str] = []
    targets: list[PurePosixPath] = []
    for mount in mounts:
        if not isinstance(mount, DockerBindMount):
            raise ValueError("Docker mounts must be DockerBindMount instances")
        raw_source = os.fspath(mount.source)
        if not raw_source:
            raise ValueError("Docker bind mount source must be non-empty")
        source_path = Path(raw_source)
        if not source_path.is_absolute():
            raise ValueError("Docker bind mount source must be absolute")
        if source_path.is_symlink():
            raise ValueError("Docker bind mount source must not be a symlink")
        source_path = source_path.resolve()
        if not source_path.is_file() and not source_path.is_dir():
            raise ValueError("Docker bind mount source must be an existing file or directory")
        source = str(source_path)
        target = _docker_bind_mount_target(mount.target, workspace_mount_target=workspace_mount_target)
        target_path = PurePosixPath(target)
        if any(portable_paths_overlap(target_path, existing) for existing in targets):
            raise ValueError(f"Docker bind mount targets overlap at: {target}")
        targets.append(target_path)
        option = f"type=bind,source={source},target={target}"
        if mount.read_only:
            option += ",readonly"
        args.extend(["--mount", option])
    return tuple(args)


def _docker_bind_mount_target(
    path: str,
    *,
    allow_workspace_root: bool = False,
    workspace_mount_target: str = "/workspace",
) -> str:
    if not isinstance(path, str) or not path or "\x00" in path:
        raise ValueError("Docker bind mount target must be a non-empty workspace path")
    if "\\" in path:
        raise ValueError(f"Docker bind mount target may not contain backslashes: {path!r}")
    candidate = PurePosixPath(path)
    if candidate.is_absolute():
        workspace_root = PurePosixPath(workspace_mount_target)
        allowed_workspace_roots = (
            workspace_root,
            PurePosixPath("/app"),
            PurePosixPath("/opt/securebench"),
            PurePosixPath("/securebench-workspace"),
            PurePosixPath("/testbed"),
        )
        if allow_workspace_root:
            if ".." in candidate.parts or str(candidate) == "/":
                raise ValueError(f"Docker workspace mount target is invalid: {path!r}")
            if not any(candidate == root or candidate.is_relative_to(root) for root in allowed_workspace_roots):
                raise ValueError(
                    "Docker workspace mount target must be under "
                    f"{', '.join(str(root) for root in allowed_workspace_roots)}: {path!r}"
                )
            return str(candidate)
        allowed_external_roots = (
            PurePosixPath("/opt/securebench"),
            PurePosixPath("/securebench-workspace"),
            PurePosixPath("/tmp"),
        )
        if candidate == workspace_root or candidate.is_relative_to(workspace_root):
            relative = candidate.relative_to(workspace_root)
            if ".." in relative.parts:
                raise ValueError(f"Docker bind mount target may not contain '..': {path!r}")
            if str(relative) in ("", "."):
                if allow_workspace_root:
                    return str(workspace_root)
                raise ValueError("Docker bind mount target must not be the workspace root")
            return str(workspace_root / relative)
        if not any(candidate == root or candidate.is_relative_to(root) for root in allowed_external_roots):
            raise ValueError(
                "Docker bind mount target must be under the configured workspace, "
                f"/opt/securebench, /securebench-workspace, or /tmp: {path!r}"
            )
        relative = candidate
    else:
        relative = candidate
    if ".." in relative.parts:
        raise ValueError(f"Docker bind mount target may not contain '..': {path!r}")
    if str(relative) in ("", "."):
        if allow_workspace_root:
            return str(PurePosixPath("/workspace"))
        raise ValueError("Docker bind mount target must not be the workspace root")
    if candidate.is_absolute():
        return str(relative)
    return str(PurePosixPath(workspace_mount_target) / relative)


def _docker_volume_mount_args(
    mounts: tuple[DockerVolumeMount, ...],
) -> tuple[str, ...]:
    args: list[str] = []
    targets: list[PurePosixPath] = []
    for mount in mounts:
        if not isinstance(mount, DockerVolumeMount):
            raise ValueError("Docker volume mounts must be DockerVolumeMount instances")
        if (
            not isinstance(mount.source, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", mount.source)
            is None
        ):
            raise ValueError("Docker volume mount source is invalid")
        if not isinstance(mount.target, str):
            raise ValueError("Docker volume mount target must be canonical, absolute, and non-root")
        target = PurePosixPath(mount.target)
        if (
            mount.target.startswith("//")
            or not target.is_absolute()
            or str(target) == "/"
            or str(target) != mount.target
            or ".." in target.parts
            or "\\" in mount.target
            or "\x00" in mount.target
        ):
            raise ValueError("Docker volume mount target must be canonical, absolute, and non-root")
        if any(portable_paths_overlap(target, existing) for existing in targets):
            raise ValueError(f"Docker volume mount targets overlap at: {mount.target}")
        targets.append(target)
        if not isinstance(mount.subpath, str):
            raise ValueError("Docker volume mount subpath must be canonical and relative")
        subpath = PurePosixPath(mount.subpath)
        if (
            subpath.is_absolute()
            or str(subpath) in ("", ".")
            or str(subpath) != mount.subpath
            or ".." in subpath.parts
            or "\\" in mount.subpath
            or "\x00" in mount.subpath
        ):
            raise ValueError("Docker volume mount subpath must be canonical and relative")
        option = (
            f"type=volume,source={mount.source},target={mount.target},"
            f"volume-subpath={mount.subpath}"
        )
        if mount.read_only:
            option += ",readonly"
        args.extend(["--mount", option])
    return tuple(args)


def _docker_hardening_args(
    *,
    network: str,
    cap_drop: tuple[str, ...],
    cap_add: tuple[str, ...],
    read_only: bool,
    tmpfs: tuple[str, ...],
    mem_limit: str | None,
    pids_limit: int | None,
    security_opt: tuple[str, ...],
) -> tuple[str, ...]:
    args: list[str] = ["--network", network]
    for capability in cap_drop:
        args.extend(["--cap-drop", capability])
    for capability in cap_add:
        args.extend(["--cap-add", capability])
    if read_only:
        args.append("--read-only")
    for mount in tmpfs:
        args.extend(["--tmpfs", mount])
    if mem_limit is not None:
        args.extend(["--memory", mem_limit])
    if pids_limit is not None:
        args.extend(["--pids-limit", str(pids_limit)])
    for option in security_opt:
        args.extend(["--security-opt", option])
    return tuple(args)


def _docker_mem_limit_override(default: str | None) -> str | None:
    value = os.environ.get(DOCKER_MEM_LIMIT_ENV)
    if value is None or value == "":
        return default
    if value.lower() in {"none", "unlimited"}:
        return None
    return value


def _docker_pids_limit_override(default: int | None) -> int | None:
    value = os.environ.get(DOCKER_PIDS_LIMIT_ENV)
    if value is None or value == "":
        return default
    if value.lower() in {"none", "unlimited"}:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{DOCKER_PIDS_LIMIT_ENV} must be an integer, none, or unlimited") from exc
    if parsed <= 0:
        raise ValueError(f"{DOCKER_PIDS_LIMIT_ENV} must be positive")
    return parsed


def _docker_tmpfs_override(default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(DOCKER_TMPFS_ENV)
    if value is None or value == "":
        return tuple(default)
    if value.lower() in {"none", "disabled"}:
        return ()
    mounts = tuple(mount.strip() for mount in value.split(";") if mount.strip())
    if not mounts:
        raise ValueError(f"{DOCKER_TMPFS_ENV} must contain at least one tmpfs mount")
    return mounts
