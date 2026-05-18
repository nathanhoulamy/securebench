"""Benchmark family contracts for candidate-producing harnesses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from securebench.errors import ConfigError


CandidateKind = Literal["text", "code", "patch"]


@dataclass(frozen=True)
class FamilyContract:
    """Minimal contract describing what candidate artifact a family expects."""

    family: str
    candidate_kind: CandidateKind
    requires_workspace: bool = False


FAMILY_CONTRACTS: dict[str, FamilyContract] = {
    "multiple_choice": FamilyContract("multiple_choice", "text"),
    "short_answer": FamilyContract("short_answer", "text"),
    "free_response": FamilyContract("free_response", "text"),
    "code_generation": FamilyContract("code_generation", "code"),
    "repo_patch": FamilyContract("repo_patch", "patch", requires_workspace=True),
}


def family_contract_for(family: str) -> FamilyContract:
    """Return the candidate-output contract for a known benchmark family."""
    contract = FAMILY_CONTRACTS.get(family)
    if contract is None:
        raise ConfigError(f"Unknown benchmark family contract: {family!r}")
    return contract


def known_family_contracts() -> tuple[FamilyContract, ...]:
    """Return all currently executable family contracts."""
    return tuple(FAMILY_CONTRACTS.values())


FamilyValidator = Callable[[Any, str], None]


def validate_benchmark_row_family(row: Any, *, context: str | None = None) -> None:
    """Validate active family-specific row fields.

    Unknown and deferred families intentionally remain permissive here so pack
    loading and compilation can keep accepting benchmark families whose runners
    are not implemented yet.
    """
    validator = FAMILY_VALIDATORS.get(row.family)
    if validator is None:
        return
    validator(row, context or f"task {row.id!r} ({row.family})")


def _validate_multiple_choice(row: Any, context: str) -> None:
    _reject_unknown(row.input, {"question", "choices"}, f"{context}.input")
    _reject_unknown(row.eval, {"answer"}, f"{context}.eval")
    _required_non_empty_string(row.input, "question", f"{context}.input")
    _required_non_empty_string_array(row.input, "choices", f"{context}.input")
    _required_string_number_or_array(row.eval, "answer", f"{context}.eval")


def _validate_short_answer(row: Any, context: str) -> None:
    _reject_unknown(row.input, {"question", "answer_format"}, f"{context}.input")
    _reject_unknown(row.eval, {"accepted_answers", "tolerance"}, f"{context}.eval")
    _required_non_empty_string(row.input, "question", f"{context}.input")
    _optional_non_empty_string(row.input, "answer_format", f"{context}.input")
    _required_non_empty_string_or_number_array(row.eval, "accepted_answers", f"{context}.eval")
    _optional_non_negative_number(row.eval, "tolerance", f"{context}.eval")


def _validate_free_response(row: Any, context: str) -> None:
    _reject_unknown(row.input, {"prompt", "context"}, f"{context}.input")
    _reject_unknown(row.eval, {"reference_answer", "rubric"}, f"{context}.eval")
    _required_non_empty_string(row.input, "prompt", f"{context}.input")
    _optional_string_or_object(row.input, "context", f"{context}.input")
    _required_string_or_object(row.eval, "rubric", f"{context}.eval")
    _optional_non_empty_string(row.eval, "reference_answer", f"{context}.eval")


def _validate_code_generation(row: Any, context: str) -> None:
    _reject_unknown(
        row.input,
        {"prompt", "language", "starter_code"},
        f"{context}.input",
    )
    _reject_unknown(
        row.eval,
        {"tests", "reference_solution", "canonical_solution"},
        f"{context}.eval",
    )
    _required_non_empty_string(row.input, "prompt", f"{context}.input")
    _optional_non_empty_string(row.input, "language", f"{context}.input")
    _optional_string(row.input, "starter_code", f"{context}.input")
    _required_object(row.eval, "tests", f"{context}.eval")
    _optional_string(row.eval, "reference_solution", f"{context}.eval")
    _optional_string(row.eval, "canonical_solution", f"{context}.eval")


def _validate_repo_patch(row: Any, context: str) -> None:
    _reject_unknown(
        row.input,
        {"repo", "base_commit", "instructions", "hints"},
        f"{context}.input",
    )
    _reject_unknown(row.eval, {"tests", "gold_patch"}, f"{context}.eval")
    _required_non_empty_string(row.input, "repo", f"{context}.input")
    _required_non_empty_string(row.input, "base_commit", f"{context}.input")
    _required_non_empty_string(row.input, "instructions", f"{context}.input")
    _optional_non_empty_string(row.input, "hints", f"{context}.input")
    _required_object(row.eval, "tests", f"{context}.eval")
    _optional_string(row.eval, "gold_patch", f"{context}.eval")


FAMILY_VALIDATORS: dict[str, FamilyValidator] = {
    "multiple_choice": _validate_multiple_choice,
    "short_answer": _validate_short_answer,
    "free_response": _validate_free_response,
    "code_generation": _validate_code_generation,
    "repo_patch": _validate_repo_patch,
}


def _reject_unknown(values: dict[str, object], allowed: set[str], context: str) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ConfigError(f"{context} has unknown field(s): {', '.join(unknown)}")


def _required(values: dict[str, object], key: str, context: str) -> object:
    if key not in values:
        raise ConfigError(f"{context}.{key} is required")
    return values[key]


def _required_non_empty_string(values: dict[str, object], key: str, context: str) -> None:
    value = _required(values, key, context)
    if not _is_non_empty_string(value):
        raise ConfigError(f"{context}.{key} must be a non-empty string")


def _optional_non_empty_string(values: dict[str, object], key: str, context: str) -> None:
    if key in values and not _is_non_empty_string(values[key]):
        raise ConfigError(f"{context}.{key} must be a non-empty string")


def _optional_string(values: dict[str, object], key: str, context: str) -> None:
    if key in values and not isinstance(values[key], str):
        raise ConfigError(f"{context}.{key} must be a string")


def _required_non_empty_string_array(values: dict[str, object], key: str, context: str) -> None:
    value = _required(values, key, context)
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{context}.{key} must be a non-empty string array")
    if not all(_is_non_empty_string(item) for item in value):
        raise ConfigError(f"{context}.{key} must contain only non-empty strings")


def _required_non_empty_string_or_number_array(
    values: dict[str, object],
    key: str,
    context: str,
) -> None:
    value = _required(values, key, context)
    if not isinstance(value, list) or not value:
        raise ConfigError(f"{context}.{key} must be a non-empty string-or-number array")
    if not all(_is_string_or_number(item) for item in value):
        raise ConfigError(f"{context}.{key} must contain only non-empty strings or numbers")


def _required_string_number_or_array(values: dict[str, object], key: str, context: str) -> None:
    value = _required(values, key, context)
    if _is_string_or_number(value):
        return
    if isinstance(value, list) and value and all(_is_string_or_number(item) for item in value):
        return
    raise ConfigError(
        f"{context}.{key} must be a non-empty string, number, or string-or-number array"
    )


def _required_object(values: dict[str, object], key: str, context: str) -> None:
    value = _required(values, key, context)
    if not isinstance(value, dict):
        raise ConfigError(f"{context}.{key} must be an object")


def _required_string_or_object(values: dict[str, object], key: str, context: str) -> None:
    value = _required(values, key, context)
    if _is_non_empty_string(value) or isinstance(value, dict):
        return
    raise ConfigError(f"{context}.{key} must be a non-empty string or object")


def _optional_string_or_object(values: dict[str, object], key: str, context: str) -> None:
    if key not in values:
        return
    value = values[key]
    if _is_non_empty_string(value) or isinstance(value, dict):
        return
    raise ConfigError(f"{context}.{key} must be a non-empty string or object")


def _optional_non_negative_number(values: dict[str, object], key: str, context: str) -> None:
    if key not in values:
        return
    value = values[key]
    if not _is_number(value) or value < 0:
        raise ConfigError(f"{context}.{key} must be a non-negative number")


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_string_or_number(value: object) -> bool:
    return _is_non_empty_string(value) or _is_number(value)
