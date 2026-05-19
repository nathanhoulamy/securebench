import pytest

from securebench.errors import ConfigError
from securebench.tasks import task_from_spec
from securebench.verifiers.multiple_choice import (
    MultipleChoiceVerifier,
    candidate_answers,
    expected_answers_for_task,
)


def make_task(*, choices=None, answer=2):
    return task_from_spec(
        {
            "id": "mmlu/math/test/7",
            "benchmark_id": "mmlu",
            "task_type": "multiple_choice",
            "resources": {
                "question": {"value": "2 + 2?", "visibility": "public"},
                "choices": {
                    "value": ["1", "2", "4", "5"] if choices is None else choices,
                    "visibility": "public",
                },
                "answer": {"value": answer, "visibility": "hidden"},
            },
        }
    )


def test_expected_numeric_answer_is_zero_based_choice_index():
    expected = expected_answers_for_task(make_task(answer=2))

    assert expected.normalized_values == {"C", "4"}


def test_expected_label_answer_accepts_label_and_choice_text():
    expected = expected_answers_for_task(make_task(answer="C"))

    assert expected.normalized_values == {"C", "4"}


@pytest.mark.parametrize("candidate", ["C", "(C)", "Answer: C", "Final answer is 4."])
def test_multiple_choice_verifier_passes_matching_candidate(candidate):
    result = MultipleChoiceVerifier().verify(make_task(answer=2), candidate)

    assert result.status == "passed"
    assert result.passed is True
    assert result.score == 1.0
    assert result.metadata["verifier"] == "multiple_choice"
    assert result.metadata["expected_answer"] == 2


def test_multiple_choice_verifier_fails_non_matching_candidate():
    result = MultipleChoiceVerifier().verify(make_task(answer="C"), "B")

    assert result.status == "failed"
    assert result.passed is False
    assert result.score == 0.0


def test_candidate_answer_parser_does_not_treat_words_containing_a_label_as_labels():
    assert "A" not in candidate_answers("The answer is 4", ("1", "2", "4", "5"))


def test_multiple_choice_verifier_rejects_invalid_index_answer():
    with pytest.raises(ConfigError, match="requires at least one valid answer"):
        MultipleChoiceVerifier().verify(make_task(answer=99), "C")
