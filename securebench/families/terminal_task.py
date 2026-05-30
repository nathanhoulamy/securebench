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
from securebench.dangerous_commands import dangerous_command_list


def validate(row: Any, context: str) -> None:
    reject_unknown(row.input, {"instructions", "context"}, f"{context}.input")
    reject_unknown(
        row.eval,
        {"checker", "run_tests", "test_files", "expected_state", "needed_commands"},
        f"{context}.eval",
    )
    required_non_empty_string(row.input, "instructions", f"{context}.input")
    optional_string_or_object(row.input, "context", f"{context}.input")
    required_object(row.eval, "checker", f"{context}.eval")
    _validate_checker(row.eval["checker"], f"{context}.eval.checker")
    dangerous_command_list(row.eval.get("needed_commands"), f"{context}.eval.needed_commands")
    if "run_tests" in row.eval:
        required_object(row.eval, "run_tests", f"{context}.eval")
    if "test_files" in row.eval:
        required_object(row.eval, "test_files", f"{context}.eval")


def _validate_checker(value: object, context: str) -> None:
    if not isinstance(value, dict):
        return
    reject_unknown(value, {"source", "path", "timeout_seconds"}, context)
    source = value.get("source")
    if source not in {"pytest", "script"}:
        raise ConfigError(f"{context}.source must be 'pytest' or 'script'")
    if not is_non_empty_string(value.get("path")):
        raise ConfigError(f"{context}.path must be a non-empty string")
    optional_positive_number(value, "timeout_seconds", context)
