from securebench.candidates import CandidateArtifact
from securebench.tasks import task_from_spec


def make_patch_task():
    return task_from_spec(
        {
            "id": "repo-1",
            "benchmark_id": "example",
            "task_type": "repo_patch",
            "resources": {
                "repo": {"value": "example/repo", "visibility": "public"},
                "base_commit": {"value": "abc123", "visibility": "public"},
                "instructions": {"value": "Fix the bug.", "visibility": "public"},
            },
        }
    )


def make_terminal_task():
    return task_from_spec(
        {
            "id": "terminal-1",
            "benchmark_id": "example",
            "task_type": "terminal_task",
            "resources": {
                "instructions": {"value": "Create output.txt.", "visibility": "public"},
                "checker": {"value": {"source": "pytest", "path": "checks"}, "visibility": "evaluation_inputs"},
            },
        }
    )


def test_candidate_artifact_returns_verifier_value_by_task_type():
    assert CandidateArtifact(patch="diff").for_task(make_patch_task()) == "diff"
    assert CandidateArtifact(workspace="/tmp/workspace").for_task(make_terminal_task()) == "/tmp/workspace"
