"""Schema validation for multiple-choice benchmark rows."""

from __future__ import annotations

from typing import Any

from securebench.families.base import (
    reject_unknown,
    required_non_empty_string,
    required_non_empty_string_array,
    required_string_number_or_array,
)


def validate(row: Any, context: str) -> None:
    reject_unknown(row.input, {"question", "choices"}, f"{context}.input")
    reject_unknown(row.eval, {"answer"}, f"{context}.eval")
    required_non_empty_string(row.input, "question", f"{context}.input")
    required_non_empty_string_array(row.input, "choices", f"{context}.input")
    required_string_number_or_array(row.eval, "answer", f"{context}.eval")
