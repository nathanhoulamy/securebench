import pytest

from securebench.runners import MultipleChoiceRunner
from securebench.runners.multiple_choice import normalize_answer, parse_choice
from securebench.tasks import CodeCompletionTask, task_from_spec


def make_task(answer=2):
    return task_from_spec(
        {
            "id": "mmlu/math/test/7",
            "benchmark_id": "mmlu",
            "task_type": "multiple_choice",
            "resources": {
                "question": {"value": "2 + 2?", "visibility": "public"},
                "choices": {"value": ["1", "2", "4", "5"], "visibility": "public"},
                "answer": {"value": answer, "visibility": "hidden"},
            },
        }
    )


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("C", "C"),
        ("c", "C"),
        ("3", "C"),
        ("The answer is C.", "C"),
        ("I choose C.", "C"),
        ("4", "D"),
    ],
)
def test_parse_choice(candidate, expected):
    assert parse_choice(candidate, ("1", "2", "3", "4")) == expected


def test_parse_choice_accepts_exact_choice_text():
    assert parse_choice("San Francisco", ("New York", "San Francisco")) == "B"


def test_parse_choice_accepts_unique_choice_text_inside_sentence():
    assert parse_choice("I would pick San Francisco.", ("New York", "San Francisco")) == "B"


def test_parse_choice_rejects_ambiguous_choice_text_inside_sentence():
    assert parse_choice("New York and York are both mentioned.", ("New York", "York")) is None


def test_normalize_answer_accepts_zero_based_index_and_letters():
    assert normalize_answer(2, ("1", "2", "4", "5")) == "C"
    assert normalize_answer("C", ("1", "2", "4", "5")) == "C"


def test_multiple_choice_runner_scores_exact_match():
    result = MultipleChoiceRunner().run(make_task(), "C")

    assert result.passed is True
    assert result.score == 1.0
    assert result.metadata == {
        "parsed_answer": "C",
        "expected_answer": "C",
    }


def test_multiple_choice_runner_scores_wrong_answer():
    result = MultipleChoiceRunner().run(make_task(), "A")

    assert result.passed is False
    assert result.score == 0.0


def test_multiple_choice_runner_rejects_wrong_task_type():
    task = CodeCompletionTask(
        id="HumanEval/0",
        benchmark_id="humaneval",
        task_type="code_completion",
    )

    with pytest.raises(TypeError, match="MultipleChoiceRunner requires MultipleChoiceTask"):
        MultipleChoiceRunner().run(task, "C")
