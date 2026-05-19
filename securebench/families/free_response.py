"""Schema validation for free-response benchmark rows."""

from __future__ import annotations

from typing import Any

from securebench.families.base import (
    optional_non_empty_string,
    optional_string_or_object,
    reject_unknown,
    required_non_empty_string,
    required_string_or_object,
)


def validate(row: Any, context: str) -> None:
    reject_unknown(row.input, {"prompt", "context"}, f"{context}.input")
    reject_unknown(row.eval, {"reference_answer", "rubric"}, f"{context}.eval")
    required_non_empty_string(row.input, "prompt", f"{context}.input")
    optional_string_or_object(row.input, "context", f"{context}.input")
    required_string_or_object(row.eval, "rubric", f"{context}.eval")
    optional_non_empty_string(row.eval, "reference_answer", f"{context}.eval")
