from securebench.candidates import CandidateArtifact
from securebench.tasks import task_from_spec


def make_text_task():
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


def test_candidate_artifact_returns_verifier_value_by_task_type():
    assert CandidateArtifact(text="C", patch="diff").for_task(make_text_task()) == "C"
    assert CandidateArtifact(text="C", patch="diff").for_task(make_patch_task()) == "diff"
