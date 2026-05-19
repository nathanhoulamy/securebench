"""Minimal command policy gate for the standalone workspace agent."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import List, Sequence, Set, Tuple, Union


class PolicyViolation(RuntimeError):
    """Raised when an agent command violates policy."""


@dataclass(frozen=True)
class CommandAttempt:
    """Audit record for an attempted command."""

    command: Tuple[str, ...]
    command_name: str
    allowed: bool
    reason: str = ""


@dataclass
class CommandPolicy:
    """Allow or deny agent commands by executable name."""

    allow: Set[str] = field(default_factory=set)
    deny: Set[str] = field(default_factory=set)
    attempts: List[CommandAttempt] = field(default_factory=list)

    def check(self, command: Union[str, Sequence[str]]) -> CommandAttempt:
        normalized = normalize_command(command)
        command_name = normalized[0] if normalized else ""

        allowed = True
        reason = ""
        if "*" in self.deny or command_name in self.deny:
            allowed = False
            reason = "Command {!r} is denied".format(command_name)
        elif self.allow and command_name not in self.allow:
            allowed = False
            reason = "Command {!r} is not in allow list".format(command_name)

        attempt = CommandAttempt(
            command=normalized,
            command_name=command_name,
            allowed=allowed,
            reason=reason,
        )
        self.attempts.append(attempt)
        return attempt

    def enforce(self, command: Union[str, Sequence[str]]) -> None:
        attempt = self.check(command)
        if not attempt.allowed:
            raise PolicyViolation(attempt.reason)


def normalize_command(command: Union[str, Sequence[str]]) -> Tuple[str, ...]:
    if isinstance(command, str):
        return tuple(shlex.split(command))
    return tuple(str(part) for part in command)
