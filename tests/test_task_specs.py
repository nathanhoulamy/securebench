import pytest

from securebench.tasks import SecureBenchTask, task_from_spec


def test_repo_patch_spec_converts_json_lists_to_task_resources():
    task = task_from_spec(
        {
            "id": "example__repo-1",
            "benchmark_id": "example",
            "task_type": "repo_patch",
            "resources": {
                "repo": {"value": "example/repo", "visibility": "public"},
                "base_commit": {"value": "abc123", "visibility": "public"},
                "instructions": {"value": "Fix it.", "visibility": "public"},
                "tests": {"value": {"source": "command", "command": ["pytest", "-q"]}, "visibility": "evaluation_inputs"},
                "gold_patch": {"value": "gold", "visibility": "hidden"},
            },
        }
    )

    assert type(task) is SecureBenchTask
    assert task.task_type == "repo_patch"
    assert task.evaluation_payload()["tests"] == {"source": "command", "command": ["pytest", "-q"]}
    assert "gold_patch" not in task.agent_payload()


def test_terminal_task_spec_converts_to_generic_securebench_task():
    task = task_from_spec(
        {
            "id": "terminal/1",
            "benchmark_id": "terminal",
            "task_type": "terminal_task",
            "resources": {
                "instructions": {"value": "Do it.", "visibility": "public"},
                "checker": {"value": {"source": "pytest", "path": "checks"}, "visibility": "evaluation_inputs"},
            },
        }
    )

    assert type(task) is SecureBenchTask
    assert task.task_type == "terminal_task"
    assert task.agent_payload() == {"instructions": "Do it."}
    assert task.evaluation_payload() == {
        "instructions": "Do it.",
        "checker": {"source": "pytest", "path": "checks"},
    }


@pytest.mark.parametrize(
    "spec, match",
    [
        ({}, "requires string field 'id'"),
        (
            {
                "id": "x",
                "benchmark_id": "b",
                "task_type": "repo_patch",
                "resources": {
                    "repo": {"value": "repo", "visibility": "public", "expose": False},
                },
            },
            "removed field 'expose'",
        ),
    ],
)
def test_task_from_spec_rejects_invalid_specs(spec, match):
    with pytest.raises(ValueError, match=match):
        task_from_spec(spec)
