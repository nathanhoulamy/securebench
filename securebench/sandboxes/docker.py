"""Docker CLI sandbox implementation."""

from __future__ import annotations

import os
import selectors
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from securebench.progress import emit_progress, wants_agent_output
from securebench.sandboxes.base import (
    CommandResult,
    Sandbox,
    resolve_sandbox_host_path,
    timeout_command_result,
    timeout_output,
)

DOCKER_MEM_LIMIT_ENV = "SECUREBENCH_DOCKER_MEM_LIMIT"
DOCKER_PIDS_LIMIT_ENV = "SECUREBENCH_DOCKER_PIDS_LIMIT"
DOCKER_TMPFS_ENV = "SECUREBENCH_DOCKER_TMPFS"


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
        workspace_mount_target: str = "/workspace",
    ) -> None:
        self.image = image
        self.env_names = tuple(env_names)
        self.env = {} if env is None else dict(env)
        self.persistent = persistent
        self.network = network
        self.cap_drop = tuple(cap_drop)
        self.cap_add = tuple(cap_add)
        self.read_only = read_only
        self.tmpfs = _docker_tmpfs_override(tmpfs)
        self.mem_limit = _docker_mem_limit_override(mem_limit)
        self.pids_limit = _docker_pids_limit_override(pids_limit)
        self.security_opt = tuple(security_opt)
        self.mounts = tuple(mounts)
        self.workspace_mount_target = _docker_bind_mount_target(workspace_mount_target, allow_workspace_root=True)
        self._container_name: str | None = None
        self._tempdir = None if root is not None else tempfile.TemporaryDirectory(prefix="securebench-")
        self.root = Path(root) if root is not None else Path(self._tempdir.name)
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
            start_result = self._ensure_container()
            if start_result is not None:
                emit_progress(
                    "sandbox_result",
                    kind="docker",
                    exit_code=start_result.exit_code,
                    command="docker run",
                    stdout=start_result.stdout,
                    stderr=start_result.stderr,
                )
                return CommandResult(
                    command=normalized,
                    exit_code=start_result.exit_code,
                    stdout=start_result.stdout,
                    stderr=start_result.stderr,
                )
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
            docker_command = [
                "docker",
                "run",
                "--rm",
                *(("-i",) if stdin is not None else ()),
                "-v",
                f"{self.root}:{self.workspace_mount_target}",
                *_docker_bind_mount_args(self.mounts, workspace_mount_target=self.workspace_mount_target),
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
            if _is_codex_agent_command(normalized) and wants_agent_output():
                if stdin is not None:
                    raise ValueError("Streaming agent commands do not support stdin")
                completed = _run_streaming_agent_command(docker_command, timeout=timeout)
            else:
                completed = subprocess.run(
                    docker_command,
                    check=False,
                    capture_output=True,
                    input=stdin,
                    text=not isinstance(stdin, bytes),
                    timeout=timeout,
                )
        except subprocess.TimeoutExpired as exc:
            if self.persistent:
                self.close()
            result = timeout_command_result(
                normalized,
                timeout,
                stdout=exc.stdout,
                stderr=exc.stderr,
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
        emit_progress(
            "sandbox_start",
            kind="docker",
            image=self.image,
            container=self._container_name,
        )
        completed = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self._container_name,
                "-v",
                f"{self.root}:{self.workspace_mount_target}",
                *_docker_bind_mount_args(self.mounts, workspace_mount_target=self.workspace_mount_target),
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


def _is_codex_agent_command(command: tuple[str, ...]) -> bool:
    return "codex exec" in " ".join(command)


def _run_streaming_agent_command(
    docker_command: list[str],
    *,
    timeout: float | None,
) -> subprocess.CompletedProcess[str]:
    started = time.monotonic()
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    process = subprocess.Popen(
        docker_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    selector = selectors.DefaultSelector()
    if process.stdout is not None:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    if process.stderr is not None:
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    try:
        while selector.get_map():
            if timeout is not None and time.monotonic() - started > timeout:
                process.kill()
                exc = subprocess.TimeoutExpired(docker_command, timeout)
                exc.stdout = "".join(stdout_parts)
                exc.stderr = "".join(stderr_parts)
                raise exc
            events = selector.select(timeout=0.2)
            if not events and process.poll() is not None:
                for key in list(selector.get_map().values()):
                    selector.unregister(key.fileobj)
                break
            for key, _ in events:
                line = key.fileobj.readline()
                if line == "":
                    selector.unregister(key.fileobj)
                    continue
                if key.data == "stdout":
                    stdout_parts.append(line)
                else:
                    stderr_parts.append(line)
                emit_progress("agent_output", stream=key.data, line=line)
        exit_code = process.wait(timeout=1)
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    return subprocess.CompletedProcess(
        docker_command,
        exit_code,
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
    )
def _docker_path(path: str, *, workspace_mount_target: str = "/workspace") -> str:
    if path.startswith("/workspace"):
        return path
    relative = PurePosixPath(path)
    if relative.is_absolute():
        return str(relative)
    return str(PurePosixPath(workspace_mount_target) / relative)


def _docker_env_args(env_names: tuple[str, ...]) -> tuple[str, ...]:
    args: list[str] = []
    for name in env_names:
        if not name or "=" in name:
            raise ValueError(f"Docker environment variable name is invalid: {name!r}")
        args.extend(["-e", name])
    return tuple(args)


def _docker_explicit_env_args(env: dict[str, str]) -> tuple[str, ...]:
    args: list[str] = []
    for name, value in env.items():
        if not name or "=" in name:
            raise ValueError(f"Docker environment variable name is invalid: {name!r}")
        args.extend(["-e", f"{name}={value}"])
    return tuple(args)


def _docker_bind_mount_args(
    mounts: tuple[DockerBindMount, ...],
    *,
    workspace_mount_target: str = "/workspace",
) -> tuple[str, ...]:
    args: list[str] = []
    for mount in mounts:
        if not isinstance(mount, DockerBindMount):
            raise ValueError("Docker mounts must be DockerBindMount instances")
        source = str(Path(mount.source))
        if not source:
            raise ValueError("Docker bind mount source must be non-empty")
        target = _docker_bind_mount_target(mount.target, workspace_mount_target=workspace_mount_target)
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
    if not isinstance(path, str) or not path:
        raise ValueError("Docker bind mount target must be a non-empty workspace path")
    if "\\" in path:
        raise ValueError(f"Docker bind mount target may not contain backslashes: {path!r}")
    candidate = PurePosixPath(path)
    if candidate.is_absolute():
        workspace_root = PurePosixPath("/workspace")
        allowed_workspace_roots = (
            workspace_root,
            PurePosixPath("/app"),
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
    return str(PurePosixPath(workspace_mount_target) / relative)


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
