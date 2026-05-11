"""Runner for multiple-choice QA tasks."""

from __future__ import annotations

import re
from typing import Any

from securebench.runners.base import Runner, RunnerResult
from securebench.tasks import MultipleChoiceTask, SecureBenchTask, resource_tuple, resource_value


class MultipleChoiceRunner(Runner):
    """Score a model response against a hidden multiple-choice answer."""

    def run(self, task: SecureBenchTask, candidate: Any, **context: Any) -> RunnerResult:
        if not isinstance(task, MultipleChoiceTask):
            raise TypeError(f"MultipleChoiceRunner requires MultipleChoiceTask, got {type(task).__name__}")

        choices = resource_tuple(task, "choices")
        expected_answer = resource_value(task, "answer")
        parsed = parse_choice(candidate, choices)
        expected = normalize_answer(expected_answer, choices)
        passed = parsed is not None and expected is not None and parsed == expected

        return RunnerResult(
            task_id=task.id,
            passed=passed,
            score=1.0 if passed else 0.0,
            metadata={
                "parsed_answer": parsed,
                "expected_answer": expected,
            },
        )


def parse_choice(candidate: Any, choices: tuple[str, ...]) -> str | None:
    """Parse a model response into a normalized choice letter."""
    if candidate is None:
        return None

    text = str(candidate).strip()
    if not text:
        return None

    direct = _letter_to_index(text)
    if direct is not None and direct < len(choices):
        return _index_to_letter(direct)

    numeric = _numeric_to_index(text)
    if numeric is not None and numeric < len(choices):
        return _index_to_letter(numeric)

    for match in re.finditer(r"\b([A-Z])\b", text.upper()):
        index = _letter_to_index(match.group(1))
        if index is not None and index < len(choices):
            return _index_to_letter(index)

    normalized_text = _normalize_text(text)
    for index, choice in enumerate(choices):
        if normalized_text == _normalize_text(choice):
            return _index_to_letter(index)

    text_matches = _choice_text_matches(text, choices)
    if len(text_matches) == 1:
        return _index_to_letter(text_matches[0])

    return None


def normalize_answer(answer: Any, choices: tuple[str, ...]) -> str | None:
    """Normalize an adapter-provided hidden answer into a choice letter."""
    if answer is None:
        return None

    if isinstance(answer, int):
        if 0 <= answer < len(choices):
            return _index_to_letter(answer)
        return None

    return parse_choice(answer, choices)


def _letter_to_index(value: str) -> int | None:
    stripped = value.strip().upper()
    if len(stripped) == 1 and "A" <= stripped <= "Z":
        return ord(stripped) - ord("A")
    return None


def _numeric_to_index(value: str) -> int | None:
    stripped = value.strip()
    if not stripped.isdigit():
        return None
    number = int(stripped)
    if number < 1:
        return None
    return number - 1


def _index_to_letter(index: int) -> str:
    return chr(ord("A") + index)


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _choice_text_matches(text: str, choices: tuple[str, ...]) -> list[int]:
    matches: list[int] = []
    for index, choice in enumerate(choices):
        normalized_choice = _normalize_text(choice)
        if not normalized_choice:
            continue
        pattern = rf"(?<!\w){re.escape(normalized_choice)}(?!\w)"
        if re.search(pattern, _normalize_text(text)):
            matches.append(index)
    return matches
