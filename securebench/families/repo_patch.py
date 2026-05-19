"""Schema validation for repo-patch benchmark rows."""

from __future__ import annotations

from typing import Any

from securebench.families.base import (
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
    reject_unknown(row.eval, {"tests", "gold_patch"}, f"{context}.eval")
    required_non_empty_string(row.input, "repo", f"{context}.input")
    required_non_empty_string(row.input, "base_commit", f"{context}.input")
    required_non_empty_string(row.input, "instructions", f"{context}.input")
    optional_non_empty_string(row.input, "hints", f"{context}.input")
    required_object(row.eval, "tests", f"{context}.eval")
    optional_string(row.eval, "gold_patch", f"{context}.eval")
