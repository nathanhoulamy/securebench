"""Sandbox interfaces for untrusted execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class CommandResult:
    """Result from a sandboxed command."""

    command: tuple[str, ...]
    exit_code: int
    stdout: str = ""
    stderr: str = ""


class Sandbox(ABC):
    """Minimal file and process API exposed to harnesses and verifiers."""

    @abstractmethod
    def run(
        self,
        command: str | list[str] | tuple[str, ...],
        *,
        workdir: str | None = None,
        timeout: float | None = None,
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

    The syntactic check rejects explicit traversal, and the resolved-path check
    blocks symlinks inside the sandbox from pointing reads or writes outside the
    sandbox root.
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
    else:
        target_resolved = target.resolve()
        if not target_resolved.is_relative_to(root_resolved):
            raise ValueError(f"Sandbox path may not escape root: {path}")
    return target
