"""Verifier for short-answer benchmark-pack tasks."""

from __future__ import annotations

import math
import re
from typing import Any

from securebench.errors import ConfigError
from securebench.tasks import SecureBenchTask, resource_value
from securebench.verifiers.base import VerificationResult, Verifier


class ShortAnswerVerifier(Verifier):
    """Compare a text candidate against hidden accepted short answers."""

    def verify(self, task: SecureBenchTask, candidate: str, **context: Any) -> VerificationResult:
        if task.task_type != "short_answer":
            raise TypeError(f"ShortAnswerVerifier requires short_answer task, got {task.task_type!r}")

        accepted = accepted_answers_for_task(task)
        tolerance = tolerance_for_task(task)
        candidate_values = candidate_answer_values(candidate)
        match = _match_candidate(candidate_values, accepted, tolerance)

        return VerificationResult(
            task_id=task.id,
            status="passed" if match is not None else "failed",
            passed=match is not None,
            score=1.0 if match is not None else 0.0,
            metadata={
                "verifier": "short_answer",
                "candidate_answer": candidate.strip(),
                "accepted_answer_count": len(accepted),
                "matched_answer_index": None if match is None else match.answer_index,
                "match_strategy": None if match is None else match.strategy,
                "tolerance": tolerance,
            },
        )


class AnswerMatch:
    def __init__(self, *, answer_index: int, strategy: str) -> None:
        self.answer_index = answer_index
        self.strategy = strategy


def accepted_answers_for_task(task: SecureBenchTask) -> tuple[object, ...]:
    answers = resource_value(task, "accepted_answers")
    if not isinstance(answers, list) or not answers:
        raise ConfigError(f"short_answer task {task.id!r} requires non-empty accepted_answers")
    if not all(_is_string_or_number(answer) for answer in answers):
        raise ConfigError(f"short_answer task {task.id!r} accepted_answers must contain only strings or numbers")
    return tuple(answers)


def tolerance_for_task(task: SecureBenchTask) -> float | None:
    tolerance = resource_value(task, "tolerance")
    if tolerance is None:
        return None
    if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or tolerance < 0:
        raise ConfigError(f"short_answer task {task.id!r} tolerance must be a non-negative number")
    return float(tolerance)


def candidate_answer_values(candidate: str) -> tuple[str, ...]:
    values = [candidate.strip()]
    focused = _focused_answer(candidate)
    if focused and focused not in values:
        values.append(focused)
    return tuple(value for value in values if value)


def _match_candidate(
    candidate_values: tuple[str, ...],
    accepted_answers: tuple[object, ...],
    tolerance: float | None,
) -> AnswerMatch | None:
    for candidate in candidate_values:
        candidate_number = _number(candidate)
        candidate_normalized = _normalize_text(candidate)
        for index, answer in enumerate(accepted_answers):
            answer_number = _number(answer)
            if tolerance is not None and candidate_number is not None and answer_number is not None:
                if math.isclose(candidate_number, answer_number, abs_tol=tolerance):
                    return AnswerMatch(answer_index=index, strategy="numeric_tolerance")
            answer_normalized = _normalize_text(str(answer))
            if candidate_normalized == answer_normalized:
                return AnswerMatch(answer_index=index, strategy="normalized_exact")
            if answer_normalized and _contains_answer(candidate_normalized, answer_normalized):
                return AnswerMatch(answer_index=index, strategy="answer_span")
    return None


def _focused_answer(candidate: str) -> str | None:
    lines = [line.strip() for line in candidate.strip().splitlines() if line.strip()]
    if not lines:
        return None
    last_line = lines[-1]
    match = re.search(
        r"(?i)(?:final\s+answer|answer)\s*(?:is)?\s*[:\-]?\s*(.+)$",
        last_line,
    )
    if match is not None:
        return match.group(1).strip()
    return last_line


def _contains_answer(candidate: str, answer: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(answer)}(?!\w)", candidate) is not None


def _normalize_text(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" \t\r\n\"'`.,;:")
    return value


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip().replace(",", "")
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text)
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _is_string_or_number(value: object) -> bool:
    return isinstance(value, str) or (isinstance(value, (int, float)) and not isinstance(value, bool))
