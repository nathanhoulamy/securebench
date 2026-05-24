"""Schema validation for terminal benchmark rows."""

from __future__ import annotations

from typing import Any

from securebench.errors import ConfigError
from securebench.families.base import (
    is_non_empty_string,
    optional_positive_number,
    optional_string_or_object,
    reject_unknown,
    required_non_empty_string,
    required_object,
)


def validate(row: Any, context: str) -> None:
    reject_unknown(row.input, {"instructions", "context"}, f"{context}.input")
    reject_unknown(row.eval, {"checker", "run_tests", "test_files", "expected_state"}, f"{context}.eval")
    required_non_empty_string(row.input, "instructions", f"{context}.input")
    optional_string_or_object(row.input, "context", f"{context}.input")
    required_object(row.eval, "checker", f"{context}.eval")
    _validate_checker(row.eval["checker"], f"{context}.eval.checker")
    if "run_tests" in row.eval:
        required_object(row.eval, "run_tests", f"{context}.eval")
    if "test_files" in row.eval:
        required_object(row.eval, "test_files", f"{context}.eval")


def _validate_checker(value: object, context: str) -> None:
    if not isinstance(value, dict):
        return
    reject_unknown(value, {"command", "workdir", "timeout_seconds"}, context)
    _required_command(value, "command", context)
    if "workdir" in value and not is_non_empty_string(value["workdir"]):
        raise ConfigError(f"{context}.workdir must be a non-empty string")
    optional_positive_number(value, "timeout_seconds", context)


def _required_command(values: dict[str, object], key: str, context: str) -> None:
    value = values.get(key)
    if is_non_empty_string(value):
        return
    if isinstance(value, list) and value and all(is_non_empty_string(item) for item in value):
        return
    raise ConfigError(f"{context}.{key} must be a non-empty string or string array")
