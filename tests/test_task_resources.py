from securebench.resources import REDACTED, Resource, ResourceBundle
from securebench.tasks import (
    CodeGenerationTask,
    GitHubPatchTask,
    MultipleChoiceTask,
    resource_tuple,
    resource_value,
    task_from_spec,
)


def multiple_choice_spec():
    return {
        "id": "mmlu/math/test/7",
        "benchmark_id": "mmlu",
        "task_type": "multiple_choice",
        "resources": {
            "question": {"value": "2 + 2?", "visibility": "public"},
            "choices": {"value": ["1", "2", "4", "5"], "visibility": "public"},
            "answer": {"value": 2, "visibility": "hidden"},
            "subject": {"value": "math", "visibility": "public"},
        },
    }


def code_generation_spec(*, tests_visibility="hidden"):
    return {
        "id": "HumanEval/0",
        "benchmark_id": "humaneval",
        "task_type": "code_generation",
        "resources": {
            "prompt": {"value": "def add(a, b):\n", "visibility": "public"},
            "language": {"value": "python", "visibility": "public"},
            "entry_point": {"value": "add", "visibility": "public"},
            "tests": {
                "value": "def check(candidate): assert candidate(1, 2) == 3",
                "visibility": tests_visibility,
            },
            "canonical_solution": {"value": "    return a + b", "visibility": "hidden"},
        },
    }


def github_patch_spec():
    return {
        "id": "example__repo-1",
        "benchmark_id": "example",
        "task_type": "github_patch",
        "resources": {
            "repo": {"value": "example/repo", "visibility": "public"},
            "base_commit": {"value": "abc123", "visibility": "public"},
            "instructions": {"value": "Fix the issue.", "visibility": "public"},
            "hints_text": {"value": "Look here.", "visibility": "public"},
            "version": {"value": "1.0", "visibility": "public"},
            "fail_to_pass": {
                "value": ["tests/test_bug.py::test_fixed"],
                "visibility": "hidden",
            },
            "pass_to_pass": {
                "value": ["tests/test_existing.py::test_ok"],
                "visibility": "hidden",
            },
            "gold_patch": {"value": "gold patch", "visibility": "hidden"},
            "test_patch": {"value": "hidden tests", "visibility": "hidden"},
            "test_groups": {
                "value": {"fail_to_pass": ["tests/test_bug.py::test_fixed"]},
                "visibility": "hidden",
            },
            "hidden_patches": {"value": {"tests": "hidden tests"}, "visibility": "hidden"},
        },
    }


def test_multiple_choice_task_agent_payload_uses_spec_resources():
    task = task_from_spec(multiple_choice_spec())

    assert isinstance(task, MultipleChoiceTask)
    assert task.agent_payload() == {
        "question": "2 + 2?",
        "choices": ["1", "2", "4", "5"],
        "subject": "math",
    }
    assert task.public_payload() == task.agent_payload()
    assert task.resources.payload_for("result")["answer"] == REDACTED
    assert task.resources.by_visibility("hidden")[0].name == "answer"


def test_code_generation_task_hides_tests_and_solution_from_spec():
    task = task_from_spec(code_generation_spec())

    assert isinstance(task, CodeGenerationTask)
    assert task.agent_payload() == {
        "prompt": "def add(a, b):\n",
        "language": "python",
        "entry_point": "add",
    }
    assert "tests" not in task.agent_payload()
    assert "canonical_solution" not in task.agent_payload()
    assert {resource.name for resource in task.resources.by_visibility("hidden")} == {
        "tests",
        "canonical_solution",
    }


def test_github_patch_task_hides_patch_and_test_resources_from_spec():
    task = task_from_spec(github_patch_spec())

    assert isinstance(task, GitHubPatchTask)
    payload = task.agent_payload()
    assert payload == {
        "repo": "example/repo",
        "base_commit": "abc123",
        "instructions": "Fix the issue.",
        "hints_text": "Look here.",
        "version": "1.0",
    }
    assert "gold_patch" not in payload
    assert "test_patch" not in payload
    assert "test_groups" not in payload
    assert "hidden_patches" not in payload
    assert {resource.name for resource in task.resources.by_visibility("hidden")} >= {
        "gold_patch",
        "test_patch",
        "test_groups",
        "hidden_patches",
    }


def test_evaluation_inputs_route_to_test_sandbox_not_agent():
    task = task_from_spec(code_generation_spec(tests_visibility="evaluation_inputs"))

    assert "tests" not in task.agent_payload()
    assert task.evaluation_payload()["tests"] == "def check(candidate): assert candidate(1, 2) == 3"
    assert [resource.name for resource in task.resources.by_visibility("evaluation_inputs")] == ["tests"]


def test_direct_task_construction_requires_explicit_resources_for_payloads():
    task = MultipleChoiceTask(
        id="mmlu/math/test/7",
        benchmark_id="mmlu",
        task_type="multiple_choice",
    )

    assert task.agent_payload() == {}
    assert task.resources.resources == {}
    assert resource_value(task, "question", "") == ""
    assert resource_tuple(task, "choices") == ()
    assert resource_value(task, "answer") is None

    task_with_resources = MultipleChoiceTask(
        id="mmlu/math/test/7",
        benchmark_id="mmlu",
        task_type="multiple_choice",
        resources=ResourceBundle(
            (
                Resource("question", "2 + 2?", "public"),
                Resource("choices", ["1", "2", "4", "5"], "public"),
                Resource("answer", 2, "hidden"),
            )
        ),
    )

    assert resource_value(task_with_resources, "question") == "2 + 2?"
    assert resource_tuple(task_with_resources, "choices") == ("1", "2", "4", "5")
    assert resource_value(task_with_resources, "answer") == 2
    assert task_with_resources.agent_payload() == {
        "question": "2 + 2?",
        "choices": ["1", "2", "4", "5"],
    }
