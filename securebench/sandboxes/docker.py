"""Docker CLI sandbox implementation."""

from __future__ import annotations

import subprocess
import tempfile
import uuid
from pathlib import Path, PurePosixPath

from securebench.sandboxes.base import CommandResult, Sandbox


class DockerSandbox(Sandbox):
    """Run commands in a Docker-backed workspace."""

    def __init__(
        self,
        *,
        image: str = "python:3.11-slim",
        root: str | Path | None = None,
        env_names: tuple[str, ...] = (),
        persistent: bool = True,
    ) -> None:
        self.image = image
        self.env_names = tuple(env_names)
        self.persistent = persistent
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
                f"{self.root}:/workspace",
                "-w",
                docker_workdir,
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
        target = self._host_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)

    def read_file(self, path: str | PurePosixPath) -> str:
        return self._host_path(path).read_text()

    def extract_file(self, path: str | PurePosixPath) -> bytes:
        return self._host_path(path).read_bytes()

    def _host_path(self, path: str | PurePosixPath) -> Path:
        sandbox_path = PurePosixPath(path)
        if sandbox_path.is_absolute():
            sandbox_path = PurePosixPath(*sandbox_path.parts[1:])
        if ".." in sandbox_path.parts:
            raise ValueError(f"Sandbox path may not escape root: {path}")
        return self.root.joinpath(*sandbox_path.parts)

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
                f"{self.root}:/workspace",
                "-w",
                "/workspace",
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
        relative = PurePosixPath(*relative.parts[1:])
    return str(PurePosixPath("/workspace") / relative)


def _docker_env_args(env_names: tuple[str, ...]) -> tuple[str, ...]:
    args: list[str] = []
    for name in env_names:
        if not name or "=" in name:
            raise ValueError(f"Docker environment variable name is invalid: {name!r}")
        args.extend(["-e", name])
    return tuple(args)
