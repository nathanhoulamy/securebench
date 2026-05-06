import pytest

from securebench.tasks import CodeGenerationTask, GitHubPatchTask, MultipleChoiceTask, task_from_spec


def test_multiple_choice_spec_converts_to_task_with_visibility():
    task = task_from_spec(
        {
            "id": "mmlu/math/test/7",
            "benchmark_id": "mmlu",
            "task_type": "multiple_choice",
            "metadata": {"split": "test"},
            "resources": {
                "question": {"value": "2 + 2?", "visibility": "public"},
                "choices": {"value": ["1", "2", "4", "5"], "visibility": "public"},
                "answer": {"value": 2, "visibility": "hidden"},
                "subject": {"value": "math", "visibility": "public"},
            },
        }
    )

    assert isinstance(task, MultipleChoiceTask)
    assert task.agent_payload() == {
        "question": "2 + 2?",
        "choices": ["1", "2", "4", "5"],
        "subject": "math",
    }
    assert [resource.name for resource in task.resources.by_visibility("hidden")] == ["answer"]


def test_code_generation_spec_converts_to_task_with_hidden_tests():
    task = task_from_spec(
        {
            "id": "HumanEval/0",
            "benchmark_id": "humaneval",
            "task_type": "code_generation",
            "resources": {
                "prompt": {"value": "def add(a, b):\n", "visibility": "public"},
                "language": {"value": "python", "visibility": "public"},
                "entry_point": {"value": "add", "visibility": "public"},
                "tests": {"value": "def check(candidate): assert True", "visibility": "hidden"},
                "canonical_solution": {"value": "    return a + b", "visibility": "hidden"},
            },
        }
    )

    assert isinstance(task, CodeGenerationTask)
    assert "tests" not in task.agent_payload()
    assert "canonical_solution" not in task.agent_payload()
    assert {resource.name for resource in task.resources.by_visibility("hidden")} == {
        "tests",
        "canonical_solution",
    }


def test_github_patch_spec_converts_json_lists_to_runner_fields():
    task = task_from_spec(
        {
            "id": "example__repo-1",
            "benchmark_id": "example",
            "task_type": "github_patch",
            "resources": {
                "repo": {"value": "example/repo", "visibility": "public"},
                "base_commit": {"value": "abc123", "visibility": "public"},
                "instructions": {"value": "Fix it.", "visibility": "public"},
                "fail_to_pass": {"value": ["tests/test_bug.py::test_fixed"], "visibility": "hidden"},
                "test_groups": {
                    "value": {"fail_to_pass": ["tests/test_bug.py::test_fixed"]},
                    "visibility": "hidden",
                },
                "gold_patch": {"value": "gold", "visibility": "hidden"},
            },
        }
    )

    assert isinstance(task, GitHubPatchTask)
    assert task.fail_to_pass == ("tests/test_bug.py::test_fixed",)
    assert task.test_groups == {"fail_to_pass": ("tests/test_bug.py::test_fixed",)}
    assert "gold_patch" not in task.agent_payload()


@pytest.mark.parametrize(
    "spec, match",
    [
        ({}, "requires string field 'id'"),
        (
            {
                "id": "x",
                "benchmark_id": "b",
                "task_type": "missing",
                "resources": {},
            },
            "unknown task_type",
        ),
        (
            {
                "id": "x",
                "benchmark_id": "b",
                "task_type": "multiple_choice",
                "resources": {
                    "question": {"value": "?", "visibility": "public"},
                    "choices": {"value": ["A"], "visibility": "public"},
                },
            },
            "missing required resources",
        ),
        (
            {
                "id": "x",
                "benchmark_id": "b",
                "task_type": "code_generation",
                "resources": {
                    "prompt": {"value": "def f():", "visibility": "private"},
                },
            },
            "visibility",
        ),
        (
            {
                "id": "x",
                "benchmark_id": "b",
                "task_type": "code_generation",
                "resources": {
                    "prompt": {"value": "def f():", "visibility": "public", "expose": False},
                },
            },
            "removed field 'expose'",
        ),
    ],
)
def test_task_from_spec_rejects_invalid_specs(spec, match):
    with pytest.raises(ValueError, match=match):
        task_from_spec(spec)
