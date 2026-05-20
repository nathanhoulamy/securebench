import pytest

from securebench.errors import ConfigError
from securebench.tasks import task_from_spec
from securebench.verifiers.short_answer import ShortAnswerVerifier


def make_task(*, accepted_answers=None, tolerance=None):
    eval_resources = {
        "accepted_answers": {
            "value": ["Denver Broncos"] if accepted_answers is None else accepted_answers,
            "visibility": "hidden",
        },
    }
    if tolerance is not None:
        eval_resources["tolerance"] = {"value": tolerance, "visibility": "hidden"}
    return task_from_spec(
        {
            "id": "squad-mini/0",
            "benchmark_id": "squad-mini",
            "task_type": "short_answer",
            "resources": {
                "question": {"value": "Which NFL team represented the AFC?", "visibility": "public"},
                **eval_resources,
            },
        }
    )


def test_short_answer_verifier_passes_normalized_exact_answer():
    result = ShortAnswerVerifier().verify(make_task(), "denver broncos")

    assert result.status == "passed"
    assert result.passed is True
    assert result.score == 1.0
    assert result.metadata["verifier"] == "short_answer"
    assert result.metadata["match_strategy"] == "normalized_exact"


def test_short_answer_verifier_passes_answer_span_in_sentence():
    result = ShortAnswerVerifier().verify(make_task(), "The answer is Denver Broncos.")

    assert result.status == "passed"
    assert result.metadata["match_strategy"] == "answer_span"


def test_short_answer_verifier_passes_numeric_tolerance():
    result = ShortAnswerVerifier().verify(make_task(accepted_answers=[3.14], tolerance=0.01), "Final answer: 3.145")

    assert result.status == "passed"
    assert result.metadata["match_strategy"] == "numeric_tolerance"


def test_short_answer_verifier_fails_non_matching_answer():
    result = ShortAnswerVerifier().verify(make_task(), "Carolina Panthers")

    assert result.status == "failed"
    assert result.passed is False
    assert result.score == 0.0


def test_short_answer_verifier_rejects_invalid_accepted_answers():
    with pytest.raises(ConfigError, match="accepted_answers"):
        ShortAnswerVerifier().verify(make_task(accepted_answers=[]), "answer")
