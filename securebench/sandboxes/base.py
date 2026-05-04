"""Sandbox interfaces for untrusted execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class CommandResult:
    """Result from a sandboxed command."""

    command: tuple[str, ...]
    exit_code: int
    stdout: str = ""
    stderr: str = ""


class Sandbox(ABC):
    """Minimal file and process API exposed to runners."""

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
