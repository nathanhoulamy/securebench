"""Docker CLI sandbox implementation."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from securebench.sandboxes.base import CommandResult, Sandbox


class DockerSandbox(Sandbox):
    """Run commands in disposable Docker containers backed by a host temp dir."""

    def __init__(self, *, image: str = "python:3.11-slim", root: str | Path | None = None) -> None:
        self.image = image
        self._tempdir = None if root is not None else tempfile.TemporaryDirectory(prefix="securebench-")
        self.root = Path(root) if root is not None else Path(self._tempdir.name)

    def run(
        self,
        command: str | list[str] | tuple[str, ...],
        *,
        workdir: str | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        normalized = _normalize_command(command)
        docker_workdir = _docker_path(workdir or ".")
        docker_command = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{self.root}:/workspace",
            "-w",
            docker_workdir,
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
