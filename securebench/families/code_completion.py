"""Schema validation for code-completion benchmark rows."""

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
        {"prompt", "language", "starter_code"},
        f"{context}.input",
    )
    reject_unknown(
        row.eval,
        {"tests", "reference_solution", "canonical_solution"},
        f"{context}.eval",
    )
    required_non_empty_string(row.input, "prompt", f"{context}.input")
    optional_non_empty_string(row.input, "language", f"{context}.input")
    optional_string(row.input, "starter_code", f"{context}.input")
    required_object(row.eval, "tests", f"{context}.eval")
    optional_string(row.eval, "reference_solution", f"{context}.eval")
    optional_string(row.eval, "canonical_solution", f"{context}.eval")
