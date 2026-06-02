"""Host-backed sandbox rooted at a workspace directory."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from securebench.progress import emit_progress
from securebench.sandboxes.base import (
    CommandResult,
    Sandbox,
    resolve_sandbox_host_path,
    timeout_command_result,
    timeout_output,
)


class HostSandbox(Sandbox):
    """Run commands on the host with all file access rooted in a workspace.

    This is a convenience harness mode, not a strong isolation boundary.
    """

    def __init__(
        self,
        *,
        root: str | Path | None = None,
        env_names: tuple[str, ...] = (),
    ) -> None:
        self.env_names = tuple(env_names)
        self._tempdir = None if root is not None else tempfile.TemporaryDirectory(prefix="securebench-host-")
        self.root = Path(root) if root is not None else Path(self._tempdir.name)
        self.root.mkdir(parents=True, exist_ok=True)
        emit_progress(
            "sandbox_create",
            kind="host",
            image="host",
            root=self.root,
            network="host",
            read_only=False,
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
        emit_progress(
            "sandbox_command",
            kind="host",
            image="host",
            workdir=str(self._host_path(workdir or ".")),
            command=" ".join(normalized),
        )
        try:
            completed = subprocess.run(
                normalized,
                cwd=self._host_path(workdir or "."),
                env=_host_env(self.env_names),
                check=False,
                capture_output=True,
                input=stdin,
                text=not isinstance(stdin, bytes),
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            result = timeout_command_result(
                normalized,
                timeout,
                stdout=exc.stdout,
                stderr=exc.stderr,
            )
            emit_progress(
                "sandbox_result",
                kind="host",
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
            kind="host",
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

    def close(self) -> None:
        if self._tempdir is not None:
            self._tempdir.cleanup()
            self._tempdir = None

    def __enter__(self) -> "HostSandbox":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _host_path(self, path: str | PurePosixPath, *, for_write: bool = False) -> Path:
        return resolve_sandbox_host_path(self.root, path, for_write=for_write)


def _normalize_command(command: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(command, str):
        shell = shutil.which("sh") or "/bin/sh"
        return (shell, "-lc", command)
    if not command:
        raise ValueError("Command must not be empty")
    return tuple(str(part) for part in command)


def _host_env(env_names: tuple[str, ...]) -> dict[str, str]:
    env: dict[str, str] = {}
    if "PATH" in os.environ:
        env["PATH"] = os.environ["PATH"]
    for name in env_names:
        if not name or "=" in name:
            raise ValueError(f"Invalid environment variable name: {name!r}")
        if name in os.environ:
            env[name] = os.environ[name]
    return env
