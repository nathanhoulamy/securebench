"""Docker CLI sandbox implementation."""

from __future__ import annotations

import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from securebench.sandboxes.base import CommandResult, Sandbox, resolve_sandbox_host_path


@dataclass(frozen=True)
class DockerBindMount:
    """Extra Docker bind mount for a workspace path."""

    source: str | Path
    target: str
    read_only: bool = True


class DockerSandbox(Sandbox):
    """Run commands in a Docker-backed workspace."""

    def __init__(
        self,
        *,
        image: str = "python:3.11-slim",
        root: str | Path | None = None,
        env_names: tuple[str, ...] = (),
        persistent: bool = True,
        network: str = "none",
        cap_drop: tuple[str, ...] = ("ALL",),
        read_only: bool = True,
        tmpfs: tuple[str, ...] = ("/tmp",),
        mem_limit: str | None = "1g",
        pids_limit: int | None = 256,
        security_opt: tuple[str, ...] = ("no-new-privileges:true",),
        mounts: tuple[DockerBindMount, ...] = (),
        workspace_mount_target: str = "/workspace",
    ) -> None:
        self.image = image
        self.env_names = tuple(env_names)
        self.persistent = persistent
        self.network = network
        self.cap_drop = tuple(cap_drop)
        self.read_only = read_only
        self.tmpfs = tuple(tmpfs)
        self.mem_limit = mem_limit
        self.pids_limit = pids_limit
        self.security_opt = tuple(security_opt)
        self.mounts = tuple(mounts)
        self.workspace_mount_target = _docker_bind_mount_target(workspace_mount_target, allow_workspace_root=True)
        self._container_name: str | None = None
        self._tempdir = None if root is not None else tempfile.TemporaryDirectory(prefix="securebench-")
        self.root = Path(root) if root is not None else Path(self._tempdir.name)
        self.root.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        command: str | list[str] | tuple[str, ...],
        *,
        workdir: str | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        normalized = _normalize_command(command)
        docker_workdir = _docker_path(workdir or ".")
        if self.persistent:
            start_result = self._ensure_container()
            if start_result is not None:
                return CommandResult(
                    command=normalized,
                    exit_code=start_result.exit_code,
                    stdout=start_result.stdout,
                    stderr=start_result.stderr,
                )
            docker_command = [
                "docker",
                "exec",
                "-w",
                docker_workdir,
                self._container_name or "",
                *normalized,
            ]
        else:
            docker_command = [
                "docker",
                "run",
                "--rm",
                "-v",
                f"{self.root}:{self.workspace_mount_target}",
                *_docker_bind_mount_args(self.mounts),
                "-w",
                docker_workdir,
                *_docker_hardening_args(
                    network=self.network,
                    cap_drop=self.cap_drop,
                    read_only=self.read_only,
                    tmpfs=self.tmpfs,
                    mem_limit=self.mem_limit,
                    pids_limit=self.pids_limit,
                    security_opt=self.security_opt,
                ),
                *_docker_env_args(self.env_names),
                self.image,
                *normalized,
            ]
        completed = subprocess.run(
            docker_command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CommandResult(
            command=normalized,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def close(self) -> None:
        """Remove the persistent container if it has been started."""
        if self._container_name is None:
            return
        subprocess.run(
            ["docker", "rm", "-f", self._container_name],
            check=False,
            capture_output=True,
            text=True,
        )
        self._container_name = None

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

    def _ensure_container(self) -> CommandResult | None:
        if self._container_name is not None:
            return None
        self._container_name = f"securebench-{uuid.uuid4().hex}"
        completed = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self._container_name,
                "-v",
                f"{self.root}:{self.workspace_mount_target}",
                *_docker_bind_mount_args(self.mounts),
                "-w",
                "/workspace",
                *_docker_hardening_args(
                    network=self.network,
                    cap_drop=self.cap_drop,
                    read_only=self.read_only,
                    tmpfs=self.tmpfs,
                    mem_limit=self.mem_limit,
                    pids_limit=self.pids_limit,
                    security_opt=self.security_opt,
                ),
                *_docker_env_args(self.env_names),
                self.image,
                "sleep",
                "infinity",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            self._container_name = None
            return CommandResult(
                command=("docker", "run"),
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        return None


def _normalize_command(command: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(command, str):
        return ("sh", "-lc", command)
    if not command:
        raise ValueError("Command must not be empty")
    return tuple(str(part) for part in command)


def _docker_path(path: str) -> str:
    if path.startswith("/workspace"):
        return path
    relative = PurePosixPath(path)
    if relative.is_absolute():
        return str(relative)
    return str(PurePosixPath("/workspace") / relative)


def _docker_env_args(env_names: tuple[str, ...]) -> tuple[str, ...]:
    args: list[str] = []
    for name in env_names:
        if not name or "=" in name:
            raise ValueError(f"Docker environment variable name is invalid: {name!r}")
        args.extend(["-e", name])
    return tuple(args)


def _docker_bind_mount_args(mounts: tuple[DockerBindMount, ...]) -> tuple[str, ...]:
    args: list[str] = []
    for mount in mounts:
        if not isinstance(mount, DockerBindMount):
            raise ValueError("Docker mounts must be DockerBindMount instances")
        source = str(Path(mount.source))
        if not source:
            raise ValueError("Docker bind mount source must be non-empty")
        target = _docker_bind_mount_target(mount.target)
        option = f"type=bind,source={source},target={target}"
        if mount.read_only:
            option += ",readonly"
        args.extend(["--mount", option])
    return tuple(args)


def _docker_bind_mount_target(path: str, *, allow_workspace_root: bool = False) -> str:
    if not isinstance(path, str) or not path:
        raise ValueError("Docker bind mount target must be a non-empty workspace path")
    if "\\" in path:
        raise ValueError(f"Docker bind mount target may not contain backslashes: {path!r}")
    candidate = PurePosixPath(path)
    if candidate.is_absolute():
        workspace_root = PurePosixPath("/workspace")
        allowed_external_roots = (
            PurePosixPath("/opt/securebench"),
            PurePosixPath("/securebench-workspace"),
            PurePosixPath("/tmp"),
        )
        if candidate == workspace_root or candidate.is_relative_to(workspace_root):
            relative = PurePosixPath(*candidate.parts[2:])
            if ".." in relative.parts:
                raise ValueError(f"Docker bind mount target may not contain '..': {path!r}")
            if str(relative) in ("", "."):
                if allow_workspace_root:
                    return str(workspace_root)
                raise ValueError("Docker bind mount target must not be the workspace root")
            return str(workspace_root / relative)
        if not any(candidate == root or candidate.is_relative_to(root) for root in allowed_external_roots):
            raise ValueError(f"Docker bind mount target must be under /workspace, /opt/securebench, or /tmp: {path!r}")
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
    return str(PurePosixPath("/workspace") / relative)


def _docker_hardening_args(
    *,
    network: str,
    cap_drop: tuple[str, ...],
    read_only: bool,
    tmpfs: tuple[str, ...],
    mem_limit: str | None,
    pids_limit: int | None,
    security_opt: tuple[str, ...],
) -> tuple[str, ...]:
    args: list[str] = ["--network", network]
    for capability in cap_drop:
        args.extend(["--cap-drop", capability])
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
