"""Verifier for deterministic free-response benchmark-pack rubrics."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from securebench.errors import ConfigError
from securebench.tasks import SecureBenchTask, resource_value
from securebench.verifiers.base import VerificationResult, Verifier


class FreeResponseVerifier(Verifier):
    """Score free responses against structured deterministic rubrics."""

    def verify(self, task: SecureBenchTask, candidate: str, **context: Any) -> VerificationResult:
        if task.task_type != "free_response":
            raise TypeError(f"FreeResponseVerifier requires free_response task, got {task.task_type!r}")

        rubric = contains_any_rubric(task)
        candidate_normalized = _normalize_text(candidate)
        rejected_index = _first_contained(candidate_normalized, rubric.rejected_answers)
        matched_index = _first_contained(candidate_normalized, rubric.accepted_answers)
        accepted_score, accepted_score_index = _best_token_f1(candidate, rubric.accepted_answers)
        rejected_score, rejected_score_index = _best_token_f1(candidate, rubric.rejected_answers)
        if matched_index is None and accepted_score >= rubric.min_token_f1:
            matched_index = accepted_score_index
        if rejected_index is None and rejected_score >= rubric.min_token_f1 and rejected_score >= accepted_score:
            rejected_index = rejected_score_index
        passed = matched_index is not None and rejected_index is None

        return VerificationResult(
            task_id=task.id,
            status="passed" if passed else "failed",
            passed=passed,
            score=1.0 if passed else 0.0,
            metadata={
                "verifier": "free_response",
                "rubric_type": rubric.kind,
                "candidate_answer": candidate.strip(),
                "accepted_answer_count": len(rubric.accepted_answers),
                "rejected_answer_count": len(rubric.rejected_answers),
                "matched_answer_index": matched_index,
                "rejected_answer_index": rejected_index,
                "accepted_token_f1": accepted_score,
                "rejected_token_f1": rejected_score,
                "min_token_f1": rubric.min_token_f1,
            },
        )


class ContainsAnyRubric:
    def __init__(
        self,
        *,
        kind: str,
        accepted_answers: tuple[str, ...],
        rejected_answers: tuple[str, ...],
        min_token_f1: float,
    ) -> None:
        self.kind = kind
        self.accepted_answers = accepted_answers
        self.rejected_answers = rejected_answers
        self.min_token_f1 = min_token_f1


def contains_any_rubric(task: SecureBenchTask) -> ContainsAnyRubric:
    rubric = resource_value(task, "rubric")
    if not isinstance(rubric, dict):
        raise ConfigError(
            f"free_response task {task.id!r} requires structured rubric object for deterministic verification"
        )
    kind = rubric.get("type", "contains_any")
    if kind != "contains_any":
        raise ConfigError(f"free_response task {task.id!r} unsupported rubric.type {kind!r}")
    accepted = _string_tuple(rubric.get("accepted_answers"), "rubric.accepted_answers", task.id)
    rejected = _optional_string_tuple(rubric.get("rejected_answers"), "rubric.rejected_answers", task.id)
    min_token_f1 = _optional_unit_float(rubric.get("min_token_f1", 1.0), "rubric.min_token_f1", task.id)
    return ContainsAnyRubric(
        kind=kind,
        accepted_answers=accepted,
        rejected_answers=rejected,
        min_token_f1=min_token_f1,
    )


def _first_contained(candidate: str, answers: tuple[str, ...]) -> int | None:
    for index, answer in enumerate(answers):
        normalized = _normalize_text(answer)
        if normalized and re.search(rf"(?<!\w){re.escape(normalized)}(?!\w)", candidate):
            return index
    return None


def _string_tuple(value: object, field: str, task_id: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError(f"free_response task {task_id!r} requires non-empty {field}")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ConfigError(f"free_response task {task_id!r} {field} must contain only non-empty strings")
    return tuple(item.strip() for item in value)


def _optional_string_tuple(value: object, field: str, task_id: str) -> tuple[str, ...]:
    if value is None:
        return ()
    return _string_tuple(value, field, task_id)


def _optional_unit_float(value: object, field: str, task_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ConfigError(f"free_response task {task_id!r} {field} must be a number between 0 and 1")
    return float(value)


def _best_token_f1(candidate: str, answers: tuple[str, ...]) -> tuple[float, int | None]:
    best_score = 0.0
    best_index = None
    for index, answer in enumerate(answers):
        score = _token_f1(candidate, answer)
        if score > best_score:
            best_score = score
            best_index = index
    return best_score, best_index


def _token_f1(candidate: str, answer: str) -> float:
    candidate_tokens = _tokens(candidate)
    answer_tokens = _tokens(answer)
    if not candidate_tokens or not answer_tokens:
        return 0.0
    common = sum((Counter(candidate_tokens) & Counter(answer_tokens)).values())
    if common == 0:
        return 0.0
    precision = common / len(candidate_tokens)
    recall = common / len(answer_tokens)
    return 2 * precision * recall / (precision + recall)


def _tokens(value: str) -> list[str]:
    value = value.lower().replace("u.s.", "united states")
    return [
        token
        for token in re.findall(r"[a-z0-9]+", value)
        if token not in STOPWORDS
    ]


def _normalize_text(value: str) -> str:
    value = value.strip().lower().replace("u.s.", "united states")
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" \t\r\n\"'`.,;:")
    return value


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "by",
    "did",
    "do",
    "does",
    "due",
    "for",
    "from",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "no",
    "not",
    "of",
    "on",
    "or",
    "over",
    "that",
    "the",
    "their",
    "this",
    "through",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "whom",
    "whose",
    "why",
    "with",
    "you",
    "your",
}
