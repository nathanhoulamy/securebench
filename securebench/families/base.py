"""Shared benchmark family contracts and schema helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, TypeGuard

from securebench.errors import ConfigError


CandidateKind = Literal["patch", "workspace"]
FamilyValidator = Callable[[Any, str], None]


@dataclass(frozen=True)
class FamilyContract:
    """Minimal contract describing what candidate artifact a family expects."""

    family: str
    candidate_kind: CandidateKind
    requires_workspace: bool = False


def reject_unknown(values: dict[str, object], allowed: set[str], context: str) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ConfigError(f"{context} has unknown field(s): {', '.join(unknown)}")


def required(values: dict[str, object], key: str, context: str) -> object:
    if key not in values:
        raise ConfigError(f"{context}.{key} is required")
    return values[key]


def required_non_empty_string(
    values: dict[str, object], key: str, context: str
) -> None:
    value = required(values, key, context)
    if not is_non_empty_string(value):
        raise ConfigError(f"{context}.{key} must be a non-empty string")


def optional_non_empty_string(
    values: dict[str, object], key: str, context: str
) -> None:
    if key in values and not is_non_empty_string(values[key]):
        raise ConfigError(f"{context}.{key} must be a non-empty string")


def optional_string(values: dict[str, object], key: str, context: str) -> None:
    if key in values and not isinstance(values[key], str):
        raise ConfigError(f"{context}.{key} must be a string")


def required_object(values: dict[str, object], key: str, context: str) -> None:
    value = required(values, key, context)
    if not isinstance(value, dict):
        raise ConfigError(f"{context}.{key} must be an object")


def optional_string_or_object(
    values: dict[str, object], key: str, context: str
) -> None:
    if key not in values:
        return
    value = values[key]
    if is_non_empty_string(value) or isinstance(value, dict):
        return
    raise ConfigError(f"{context}.{key} must be a non-empty string or object")


def optional_non_negative_number(
    values: dict[str, object], key: str, context: str
) -> None:
    if key not in values:
        return
    value = values[key]
    if not is_number(value) or value < 0:
        raise ConfigError(f"{context}.{key} must be a non-negative number")


def optional_positive_number(
    values: dict[str, object], key: str, context: str
) -> None:
    if key not in values:
        return
    value = values[key]
    if not is_number(value) or value <= 0:
        raise ConfigError(f"{context}.{key} must be a positive number")


def is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
