"""Sandbox interfaces for untrusted execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


TIMEOUT_EXIT_CODE = 124


@dataclass(frozen=True)
class CommandResult:
    """Result from a sandboxed command."""

    command: tuple[str, ...]
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    timeout_seconds: float | None = None


def timeout_command_result(
    command: tuple[str, ...],
    timeout: float | None,
    *,
    stdout: str | bytes | None = None,
    stderr: str | bytes | None = None,
) -> CommandResult:
    """Build a structured result for a sandbox command timeout."""
    return CommandResult(
        command=command,
        exit_code=TIMEOUT_EXIT_CODE,
        stdout=timeout_output(stdout),
        stderr=timeout_output(stderr),
        timed_out=True,
        timeout_seconds=timeout,
    )


def timeout_output(value: str | bytes | None) -> str:
    """Normalize partial timeout output from subprocess APIs."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


class Sandbox(ABC):
    """Minimal file and process API exposed to harnesses and verifiers."""

    @abstractmethod
    def run(
        self,
        command: str | list[str] | tuple[str, ...],
        *,
        workdir: str | None = None,
        timeout: float | None = None,
        stdin: str | bytes | None = None,
    ) -> CommandResult:
        """Run a command in the sandbox."""

    @abstractmethod
    def write_file(self, path: str | PurePosixPath, content: str | bytes) -> None:
        """Write a file inside the sandbox."""

    @abstractmethod
    def read_file(self, path: str | PurePosixPath) -> str:
        """Read a text file from the sandbox."""

    @abstractmethod
    def extract_file(self, path: str | PurePosixPath) -> bytes:
        """Extract a file from the sandbox as bytes."""


def resolve_sandbox_host_path(
    root: str | Path,
    path: str | PurePosixPath,
    *,
    for_write: bool = False,
) -> Path:
    """Resolve a sandbox-relative host path without following escapes.

    The syntactic check rejects explicit traversal, the resolved-path check
    blocks symlinks inside the sandbox from pointing reads or writes outside the
    sandbox root, and write resolution rejects existing symlink components so
    framework-owned writes cannot be redirected within the workspace.
    """
    sandbox_path = PurePosixPath(path)
    if sandbox_path.is_absolute():
        sandbox_path = PurePosixPath(*sandbox_path.parts[1:])
    if ".." in sandbox_path.parts:
        raise ValueError(f"Sandbox path may not escape root: {path}")

    root_path = Path(root)
    target = root_path.joinpath(*sandbox_path.parts)
    root_resolved = root_path.resolve()
    if for_write:
        parent_resolved = target.parent.resolve()
        if not parent_resolved.is_relative_to(root_resolved):
            raise ValueError(f"Sandbox path may not escape root: {path}")
        if target.exists() or target.is_symlink():
            target_resolved = target.resolve()
            if not target_resolved.is_relative_to(root_resolved):
                raise ValueError(f"Sandbox path may not escape root: {path}")
        _reject_write_symlinks(root_path, sandbox_path)
    else:
        target_resolved = target.resolve()
        if not target_resolved.is_relative_to(root_resolved):
            raise ValueError(f"Sandbox path may not escape root: {path}")
    return target


def _reject_write_symlinks(root: Path, relative_path: PurePosixPath) -> None:
    current = root
    for part in relative_path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Sandbox path may not write through symlink: {relative_path}")
        if not current.exists():
            break
