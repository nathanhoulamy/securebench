"""Schema validation for repo-patch benchmark rows."""

from __future__ import annotations

from typing import Any

from securebench.errors import ConfigError
from securebench.families.base import (
    is_non_empty_string,
    optional_non_negative_number,
    optional_non_empty_string,
    optional_string,
    reject_unknown,
    required_non_empty_string,
    required_object,
)


def validate(row: Any, context: str) -> None:
    reject_unknown(
        row.input,
        {"repo", "base_commit", "instructions", "hints"},
        f"{context}.input",
    )
    reject_unknown(row.eval, {"tests", "candidate_policy", "gold_patch"}, f"{context}.eval")
    required_non_empty_string(row.input, "repo", f"{context}.input")
    required_non_empty_string(row.input, "base_commit", f"{context}.input")
    required_non_empty_string(row.input, "instructions", f"{context}.input")
    optional_non_empty_string(row.input, "hints", f"{context}.input")
    required_object(row.eval, "tests", f"{context}.eval")
    optional_string(row.eval, "gold_patch", f"{context}.eval")
    if "candidate_policy" in row.eval:
        _validate_candidate_policy(row.eval["candidate_policy"], f"{context}.eval.candidate_policy")
    _validate_command_tests(row.eval["tests"], f"{context}.eval.tests")


def _validate_command_tests(tests: object, context: str) -> None:
    if not isinstance(tests, dict):
        return
    reject_unknown(
        tests,
        {
            "source",
            "command",
            "workdir",
            "timeout_seconds",
            "setup_patch",
            "test_patch",
        },
        context,
    )
    source = tests.get("source")
    if source != "command":
        raise ConfigError(f"{context}.source must be 'command'")
    _required_command(tests, "command", context)
    optional_non_empty_string(tests, "workdir", context)
    optional_non_negative_number(tests, "timeout_seconds", context)
    if "setup_patch" in tests:
        _validate_test_patch(tests["setup_patch"], f"{context}.setup_patch")
    if "test_patch" in tests:
        _validate_test_patch(tests["test_patch"], f"{context}.test_patch")


def _required_command(values: dict[str, object], key: str, context: str) -> None:
    value = values.get(key)
    if is_non_empty_string(value):
        return
    if isinstance(value, list) and value and all(is_non_empty_string(item) for item in value):
        return
    raise ConfigError(f"{context}.{key} must be a non-empty string or string array")


def _validate_test_patch(value: object, context: str) -> None:
    if is_non_empty_string(value):
        return
    if not isinstance(value, dict):
        raise ConfigError(f"{context} must be a non-empty string or inline patch object")
    reject_unknown(value, {"source", "patch"}, context)
    if value.get("source") != "inline":
        raise ConfigError(f"{context}.source must be 'inline'")
    if not is_non_empty_string(value.get("patch")):
        raise ConfigError(f"{context}.patch must be a non-empty string")


def _validate_candidate_policy(value: object, context: str) -> None:
    if not isinstance(value, dict):
        raise ConfigError(f"{context} must be an object")
    reject_unknown(value, {"allow_paths", "allow_sensitive_paths", "patch_preserved_paths"}, context)
    if "allow_paths" in value:
        _validate_policy_paths(value["allow_paths"], f"{context}.allow_paths")
    if "allow_sensitive_paths" in value:
        _validate_policy_paths(value["allow_sensitive_paths"], f"{context}.allow_sensitive_paths")
    if "patch_preserved_paths" in value:
        _validate_policy_paths(value["patch_preserved_paths"], f"{context}.patch_preserved_paths")


def _validate_policy_paths(value: object, context: str) -> None:
    if not isinstance(value, list) or not all(is_non_empty_string(item) for item in value):
        raise ConfigError(f"{context} must be a string array")
