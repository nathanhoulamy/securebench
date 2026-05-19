"""Verifier for multiple-choice benchmark-pack tasks."""

from __future__ import annotations

import re
import string
from typing import Any

from securebench.errors import ConfigError
from securebench.tasks import MultipleChoiceTask, SecureBenchTask, resource_value
from securebench.verifiers.base import VerificationResult, Verifier


class MultipleChoiceVerifier(Verifier):
    """Compare a text candidate against hidden multiple-choice answers."""

    def verify(
        self, task: SecureBenchTask, candidate: str, **context: Any
    ) -> VerificationResult:
        if not isinstance(task, MultipleChoiceTask):
            raise TypeError(
                f"MultipleChoiceVerifier requires MultipleChoiceTask, got {type(task).__name__}"
            )

        choices = choices_for_task(task)
        expected = expected_answers_for_task(task, choices)
        candidate_values = candidate_answers(candidate, choices)
        passed = bool(candidate_values & expected.normalized_values)

        return VerificationResult(
            task_id=task.id,
            status="passed" if passed else "failed",
            passed=passed,
            score=1.0 if passed else 0.0,
            metadata={
                "verifier": "multiple_choice",
                "candidate_answer": candidate.strip(),
                "expected_answer": expected.raw_answer,
            },
        )


class ExpectedAnswers:
    def __init__(self, *, raw_answer: object, normalized_values: set[str]) -> None:
        self.raw_answer = raw_answer
        self.normalized_values = normalized_values


def choices_for_task(task: MultipleChoiceTask) -> tuple[str, ...]:
    """Return public choices as non-empty strings."""
    choices = resource_value(task, "choices")
    if not isinstance(choices, list) or not choices:
        raise ConfigError(f"MultipleChoiceTask {task.id!r} requires non-empty choices")
    if not all(isinstance(choice, str) and choice.strip() for choice in choices):
        raise ConfigError(
            f"MultipleChoiceTask {task.id!r} choices must contain only non-empty strings"
        )
    if len(choices) > len(string.ascii_uppercase):
        raise ConfigError("MultipleChoiceVerifier supports at most 26 choices")
    return tuple(choice.strip() for choice in choices)


def expected_answers_for_task(
    task: MultipleChoiceTask, choices: tuple[str, ...] | None = None
) -> ExpectedAnswers:
    """Return normalized accepted answer labels and choice text values."""
    choices = choices_for_task(task) if choices is None else choices
    raw_answer = resource_value(task, "answer")
    raw_answers = raw_answer if isinstance(raw_answer, list) else [raw_answer]
    normalized_values: set[str] = set()

    for answer in raw_answers:
        normalized_values.update(_answer_values(answer, choices))

    if not normalized_values:
        raise ConfigError(
            f"MultipleChoiceTask {task.id!r} requires at least one valid answer"
        )
    return ExpectedAnswers(raw_answer=raw_answer, normalized_values=normalized_values)


def candidate_answers(candidate: str, choices: tuple[str, ...]) -> set[str]:
    """Return normalized answer values parsed from candidate text."""
    if not candidate.strip():
        return set()
    values = {_normalize_text(candidate)}

    focused = _focused_answer(candidate)
    if focused:
        values.add(_normalize_text(focused))
        label = _label_value(focused, choices)
        if label is not None:
            values.add(label)

    label = _label_value(candidate, choices)
    if label is not None:
        values.add(label)
    return {value for value in values if value}


def _answer_values(answer: object, choices: tuple[str, ...]) -> set[str]:
    if isinstance(answer, bool):
        return set()
    if isinstance(answer, int):
        return _choice_values(answer, choices)
    if isinstance(answer, float) and answer.is_integer():
        return _choice_values(int(answer), choices)
    if isinstance(answer, str):
        value = answer.strip()
        label = _label_value(value, choices)
        if label is not None:
            index = string.ascii_uppercase.index(label)
            return {label, _normalize_text(choices[index])}
        values = {_normalize_text(value)}
        for index, choice in enumerate(choices):
            if _normalize_text(choice) == _normalize_text(value):
                values.add(string.ascii_uppercase[index])
        return values
    return set()


def _choice_values(index: int, choices: tuple[str, ...]) -> set[str]:
    if index < 0 or index >= len(choices):
        return set()
    return {string.ascii_uppercase[index], _normalize_text(choices[index])}


def _label_value(value: str, choices: tuple[str, ...]) -> str | None:
    match = re.fullmatch(
        r"\s*(?:final\s+answer|answer|choice|option)?\s*(?:is)?\s*[:\-]?\s*[\(\[]?([A-Za-z])[\)\].:]?\s*",
        value,
    )
    if match is None:
        return None
    label = match.group(1).upper()
    if string.ascii_uppercase.index(label) >= len(choices):
        return None
    return label


def _focused_answer(candidate: str) -> str | None:
    lines = [line.strip() for line in candidate.strip().splitlines() if line.strip()]
    if not lines:
        return None
    last_line = lines[-1]
    match = re.search(
        r"(?i)(?:final\s+answer|answer|choice|option)\s*(?:is)?\s*[:\-]?\s*(.+)$",
        last_line,
    )
    if match is not None:
        return match.group(1).strip()
    return last_line


def _normalize_text(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" \t\r\n\"'`.,;:")
    return value
