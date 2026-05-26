"""Verifier-only dangerous command allowance policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from securebench.errors import ConfigError


KNOWN_DANGEROUS_COMMANDS = {
    "chroot": ("SYS_CHROOT",),
}


@dataclass(frozen=True)
class VerificationPolicy:
    """Tester-owned verifier sandbox policy."""

    disallow_dangerous_commands: bool = True
    deny_commands: tuple[str, ...] = ()


@dataclass(frozen=True)
class DangerousCommandDecision:
    """Effective verifier dangerous command policy decision."""

    allowed: bool
    needed_commands: tuple[str, ...]
    denied_commands: tuple[str, ...] = ()
    cap_add: tuple[str, ...] = ()
    reason: str = ""


def parse_verification_policy(value: Any, *, field: str = "verification") -> VerificationPolicy:
    """Parse tester-owned verifier sandbox policy."""
    if value is None:
        return VerificationPolicy()
    if not isinstance(value, dict):
        raise ConfigError(f"{field} must be an object")
    _reject_unknown_fields(value, {"disallow_dangerous_commands", "deny_commands"}, field)

    disallow = value.get("disallow_dangerous_commands", True)
    if not isinstance(disallow, bool):
        raise ConfigError(f"{field}.disallow_dangerous_commands must be a boolean")

    return VerificationPolicy(
        disallow_dangerous_commands=disallow,
        deny_commands=dangerous_command_list(value.get("deny_commands"), f"{field}.deny_commands"),
    )


def dangerous_command_list(value: Any, field: str) -> tuple[str, ...]:
    """Parse and validate known dangerous command identifiers."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigError(f"{field} must be a list of known dangerous command names")
    commands = []
    seen = set()
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"{field}[{index}] must be a non-empty dangerous command name")
        command = item.strip()
        if command not in KNOWN_DANGEROUS_COMMANDS:
            known = ", ".join(sorted(KNOWN_DANGEROUS_COMMANDS))
            raise ConfigError(f"{field}[{index}] must be one of: {known}")
        if command not in seen:
            commands.append(command)
            seen.add(command)
    return tuple(commands)


def resolve_dangerous_commands(
    needed_commands: tuple[str, ...],
    policy: VerificationPolicy | None,
) -> DangerousCommandDecision:
    """Resolve benchmark-needed dangerous commands against tester policy."""
    policy = policy or VerificationPolicy()
    if not needed_commands:
        return DangerousCommandDecision(allowed=True, needed_commands=())

    denied_by_tester = tuple(command for command in needed_commands if command in policy.deny_commands)
    if denied_by_tester:
        names = ", ".join(denied_by_tester)
        return DangerousCommandDecision(
            allowed=False,
            needed_commands=needed_commands,
            denied_commands=denied_by_tester,
            reason=f"dangerous verifier command denied by tester policy: {names}",
        )

    if policy.disallow_dangerous_commands:
        return DangerousCommandDecision(
            allowed=False,
            needed_commands=needed_commands,
            denied_commands=needed_commands,
            reason="dangerous verifier commands are disabled by tester policy",
        )

    cap_add = []
    for command in needed_commands:
        for capability in KNOWN_DANGEROUS_COMMANDS[command]:
            if capability not in cap_add:
                cap_add.append(capability)
    return DangerousCommandDecision(
        allowed=True,
        needed_commands=needed_commands,
        cap_add=tuple(cap_add),
    )


def _reject_unknown_fields(data: dict[str, Any], allowed: set[str], section: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        names = ", ".join(unknown)
        raise ConfigError(f"{section} contains unsupported field(s): {names}")
