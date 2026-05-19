"""Minimal command policy gate for sandbox execution."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from securebench.sandboxes.base import CommandResult, Sandbox


class PolicyViolation(RuntimeError):
    """Raised when a sandbox command violates policy."""


@dataclass(frozen=True)
class CommandAttempt:
    """Audit record for an attempted command."""

    command: tuple[str, ...]
    command_name: str
    allowed: bool
    reason: str = ""


@dataclass
class CommandPolicy:
    """Allow or deny sandbox commands by executable name."""

    allow: set[str] = field(default_factory=set)
    deny: set[str] = field(default_factory=set)
    attempts: list[CommandAttempt] = field(default_factory=list)

    def check(self, command: str | list[str] | tuple[str, ...]) -> CommandAttempt:
        normalized = normalize_command(command)
        command_name = normalized[0] if normalized else ""

        allowed = True
        reason = ""
        if "*" in self.deny or command_name in self.deny:
            allowed = False
            reason = f"Command {command_name!r} is denied"
        elif self.allow and command_name not in self.allow:
            allowed = False
            reason = f"Command {command_name!r} is not in allow list"

        attempt = CommandAttempt(
            command=normalized,
            command_name=command_name,
            allowed=allowed,
            reason=reason,
        )
        self.attempts.append(attempt)
        return attempt

    def enforce(self, command: str | list[str] | tuple[str, ...]) -> None:
        attempt = self.check(command)
        if not attempt.allowed:
            raise PolicyViolation(attempt.reason)


class PolicySandbox(Sandbox):
    """Sandbox wrapper that enforces command policy and preserves audit logs."""

    def __init__(self, sandbox: Sandbox, policy: CommandPolicy) -> None:
        self.sandbox = sandbox
        self.policy = policy

    def run(
        self,
        command: str | list[str] | tuple[str, ...],
        *,
        workdir: str | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        self.policy.enforce(command)
        return self.sandbox.run(command, workdir=workdir, timeout=timeout)

    def write_file(self, path: str | PurePosixPath, content: str | bytes) -> None:
        self.sandbox.write_file(path, content)

    def read_file(self, path: str | PurePosixPath) -> str:
        return self.sandbox.read_file(path)

    def extract_file(self, path: str | PurePosixPath) -> bytes:
        return self.sandbox.extract_file(path)


def normalize_command(command: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(command, str):
        return tuple(shlex.split(command))
    return tuple(str(part) for part in command)
