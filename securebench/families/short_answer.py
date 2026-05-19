"""Schema validation for short-answer benchmark rows."""

from __future__ import annotations

from typing import Any

from securebench.families.base import (
    optional_non_empty_string,
    optional_non_negative_number,
    reject_unknown,
    required_non_empty_string,
    required_non_empty_string_or_number_array,
)


def validate(row: Any, context: str) -> None:
    reject_unknown(row.input, {"question", "answer_format"}, f"{context}.input")
    reject_unknown(row.eval, {"accepted_answers", "tolerance"}, f"{context}.eval")
    required_non_empty_string(row.input, "question", f"{context}.input")
    optional_non_empty_string(row.input, "answer_format", f"{context}.input")
    required_non_empty_string_or_number_array(
        row.eval, "accepted_answers", f"{context}.eval"
    )
    optional_non_negative_number(row.eval, "tolerance", f"{context}.eval")
