from securebench.candidates import StaticCandidateProducer
from securebench.evaluator import evaluate_row, evaluate_task, get_runner
from securebench.runners import MultipleChoiceRunner
from securebench.tasks import task_from_spec


def make_task():
    return task_from_spec(
        {
            "id": "mmlu/math/test/7",
            "benchmark_id": "mmlu",
            "task_type": "multiple_choice",
            "resources": {
                "question": {"value": "2 + 2?", "visibility": "public"},
                "choices": {"value": ["1", "2", "4", "5"], "visibility": "public"},
                "answer": {"value": 2, "visibility": "hidden"},
            },
        }
    )


def test_get_runner_returns_builtin_runner_for_task_type():
    assert isinstance(get_runner("multiple_choice"), MultipleChoiceRunner)


def test_evaluate_task_produces_candidate_and_runs_selected_runner():
    result = evaluate_task(make_task(), StaticCandidateProducer("C"))

    assert result.passed is True
    assert result.score == 1.0
    assert result.candidate.text == "C"
    assert result.runner_result.metadata["parsed_answer"] == "C"


def test_evaluate_row_adapts_raw_row_before_producing_candidate():
    row = {
        "question": "2 + 2?",
        "subject": "math",
        "choices": ["1", "2", "4", "5"],
        "answer": 2,
    }

    result = evaluate_row(
        "mmlu",
        row,
        StaticCandidateProducer("C"),
        adapter_context={"split": "test", "row_idx": 7},
    )

    assert result.task.id == "mmlu/math/test/7"
    assert result.passed is True
