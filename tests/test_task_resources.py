from securebench.resources import REDACTED, Resource, ResourceBundle
from securebench.tasks import SecureBenchTask, resource_value, task_from_spec


def repo_patch_spec():
    return {
        "id": "example__repo-1",
        "benchmark_id": "example",
        "task_type": "repo_patch",
        "resources": {
            "repo": {"value": "example/repo", "visibility": "public"},
            "base_commit": {"value": "abc123", "visibility": "public"},
            "instructions": {"value": "Fix the issue.", "visibility": "public"},
            "hints_text": {"value": "Look here.", "visibility": "public"},
            "version": {"value": "1.0", "visibility": "public"},
            "tests": {
                "value": {"source": "command", "command": ["pytest", "-q"]},
                "visibility": "evaluation_inputs",
            },
            "gold_patch": {"value": "gold patch", "visibility": "hidden"},
        },
    }


def terminal_task_spec():
    return {
        "id": "terminal/create-output",
        "benchmark_id": "terminal",
        "task_type": "terminal_task",
        "resources": {
            "instructions": {"value": "Create output.txt.", "visibility": "public"},
            "context": {"value": {"cwd": "/workspace"}, "visibility": "public"},
            "checker": {
                "value": {"source": "pytest", "path": "checks"},
                "visibility": "evaluation_inputs",
            },
            "expected_state": {"value": {"file": "output.txt"}, "visibility": "hidden"},
        },
    }


def test_repo_patch_task_hides_patch_and_test_resources_from_agent_payload():
    task = task_from_spec(repo_patch_spec())

    assert type(task) is SecureBenchTask
    assert task.task_type == "repo_patch"
    payload = task.agent_payload()
    assert payload == {
        "repo": "example/repo",
        "base_commit": "abc123",
        "instructions": "Fix the issue.",
        "hints_text": "Look here.",
        "version": "1.0",
    }
    assert "tests" not in payload
    assert "gold_patch" not in payload
    assert task.resources.payload_for("result")["gold_patch"] == REDACTED
    assert task.evaluation_payload()["tests"] == {"source": "command", "command": ["pytest", "-q"]}


def test_terminal_task_hides_checker_and_expected_state_from_agent_payload():
    task = task_from_spec(terminal_task_spec())

    assert type(task) is SecureBenchTask
    assert task.agent_payload() == {
        "instructions": "Create output.txt.",
        "context": {"cwd": "/workspace"},
    }
    assert "checker" not in task.agent_payload()
    assert "expected_state" not in task.agent_payload()
    assert task.evaluation_payload()["checker"] == {"source": "pytest", "path": "checks"}
    assert task.hidden_payload()["expected_state"] == {"file": "output.txt"}


def test_direct_task_construction_requires_explicit_resources_for_payloads():
    task = SecureBenchTask(
        id="repo-1",
        benchmark_id="repo",
        task_type="repo_patch",
    )

    assert task.agent_payload() == {}
    assert task.resources.resources == {}
    assert resource_value(task, "instructions", "") == ""
    assert resource_value(task, "gold_patch") is None

    task_with_resources = SecureBenchTask(
        id="repo-1",
        benchmark_id="repo",
        task_type="repo_patch",
        resources=ResourceBundle(
            (
                Resource("instructions", "Fix it.", "public"),
                Resource("gold_patch", "diff", "hidden"),
            )
        ),
    )

    assert resource_value(task_with_resources, "instructions") == "Fix it."
    assert resource_value(task_with_resources, "gold_patch") == "diff"
    assert task_with_resources.agent_payload() == {"instructions": "Fix it."}
