from __future__ import annotations

from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ArtifactCheck
from securebench.verification import VerificationEngine
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_terminal_task,
    verify_command_candidate,
    verify_workspace,
)


TASK_ID = "terminal-bench/count-dataset-tokens"
IMAGE = (
    "alexgshaw/count-dataset-tokens@"
    "sha256:9c513c4ba342bd95be501f6f5eadd4806a2b18749c87c251615825100130232d"
)
EXPECTED = "79586"


def compiled_task():
    return load_terminal_task(TASK_ID)


def verify_answer(tmp_path: Path, content: str | bytes):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "tokenizer-cache.bin").write_bytes(b"excluded")
    target = workspace / "answer.txt"
    if isinstance(content, str):
        target.write_text(content, encoding="utf-8")
    else:
        target.write_bytes(content)
    return verify_workspace(
        task,
        workspace,
        tmp_path / "store",
        run_seed="count-dataset-tokens-qualification",
    )


def test_count_dataset_tokens_row_is_passive_bounded_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    assert len(task.verification.checks) == 1
    check = task.verification.checks[0]
    assert isinstance(check, ArtifactCheck)
    assert check.artifacts[0].parser == "securebench.utf8-text/v1"
    assert not task.verification.resources.runtime
    assert task.verification.candidate.max_total_files == 1
    assert task.verification.candidate.max_total_bytes == 4096
    entry = task.verification.candidate.files[0]
    assert entry.id == "answer"
    assert entry.path == "/app/answer.txt"
    assert entry.max_bytes == 4096

    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    assert {
        path.relative_to(oracle_root).as_posix()
        for path in oracle_root.rglob("*")
        if path.is_file()
    } == {"oracle.py", "oracle.yaml"}


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(EXPECTED, id="bare_count"),
        pytest.param(f"The count is {EXPECTED}.\n", id="source_substring_semantics"),
        pytest.param(f"PASS\x00{EXPECTED}\x00", id="valid_utf8_nul_and_claim"),
        pytest.param(f"0{EXPECTED}0", id="embedded_digits"),
    ],
)
def test_source_verifier_accepted_outputs_pass(tmp_path, content):
    result, candidate, store = verify_answer(tmp_path, content)

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert manifest.type == "file_bundle"
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["answer"]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("79585", id="off_by_one"),
        pytest.param("79568", id="transposed_digits"),
        pytest.param("79,586", id="comma_separated"),
        pytest.param("79 586", id="space_separated"),
        pytest.param("PASS", id="forged_verdict_without_count"),
        pytest.param('{"verdict":"pass"}', id="structured_claim_without_count"),
    ],
)
def test_targeted_mutants_and_unsupported_claims_fail(tmp_path, content):
    result, _, _ = verify_answer(tmp_path, content)

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [
        "incorrect_token_count"
    ]


def test_invalid_utf8_is_candidate_evidence_not_infrastructure(tmp_path):
    result, _, _ = verify_answer(tmp_path, EXPECTED.encode() + b"\xff")

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == ["invalid_utf8"]


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_answer(tmp_path, EXPECTED)
    second = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="count-dataset-tokens-replay",
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    ("content", "expected_status"),
    [
        pytest.param(EXPECTED, "passed", id="reference"),
        pytest.param("79585", "failed", id="off_by_one"),
        pytest.param("PASS", "failed", id="forged_verdict"),
        pytest.param(f"PASS\x00{EXPECTED}", "passed", id="source_containment"),
    ],
)
def test_pinned_agent_capture_and_replay_matrix(tmp_path, content, expected_status):
    task = compiled_task()
    script = (
        "from pathlib import Path;"
        f"Path('/app/answer.txt').write_text({content!r},encoding='utf-8')"
    )
    result, _, _ = verify_command_candidate(
        task,
        tmp_path,
        command=("python3", "-c", script),
        run_seed=f"count-dataset-tokens-pinned-{expected_status}",
    )

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
