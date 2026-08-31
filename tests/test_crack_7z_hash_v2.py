from __future__ import annotations

import hashlib
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


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/crack-7z-hash"
IMAGE = (
    "alexgshaw/crack-7z-hash@"
    "sha256:0f4453abd774c5a3d3d7e66ba28fae88ec2e49ada3a993b324ebc16c348666d3"
)
EXPECTED = "honeybear"
ARCHIVE_SHA256 = "a2e13fcbb4c2c8e92b1bf9d78ec91376705d1f5631d5bd4de64f82aa0553b773"


def compiled_task():
    return load_terminal_task(TASK_ID)


def verify_solution(tmp_path: Path, content: str | bytes):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "secret_file.txt").write_text("excluded", encoding="utf-8")
    (workspace / "john.log").write_text("excluded", encoding="utf-8")
    target = workspace / "solution.txt"
    if isinstance(content, str):
        target.write_text(content, encoding="utf-8")
    else:
        target.write_bytes(content)
    return verify_workspace(
        task,
        workspace,
        tmp_path / "store",
        run_seed="crack-7z-hash-qualification",
    )


def test_crack_7z_hash_row_is_passive_bounded_and_executable():
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
    assert entry.id == "solution"
    assert entry.path == "/app/solution.txt"
    assert entry.max_bytes == 4096

    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    assert {
        path.relative_to(oracle_root).as_posix()
        for path in oracle_root.rglob("*")
        if path.is_file()
    } == {"oracle.py", "oracle.yaml"}


def test_public_archive_identity_is_stable():
    archive = PACK / "docker" / "crack-7z-hash" / "task-deps" / "secrets.7z"
    content = archive.read_bytes()

    assert len(content) == 215
    assert content.startswith(b"7z\xbc\xaf\x27\x1c")
    assert hashlib.sha256(content).hexdigest() == ARCHIVE_SHA256


@pytest.mark.parametrize("content", [EXPECTED, f" \n\t{EXPECTED}\r\n "])
def test_reference_plaintext_passes_with_source_strip_semantics(tmp_path, content):
    result, candidate, store = verify_solution(tmp_path, content)

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert manifest.type == "file_bundle"
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["solution"]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("honeybea", id="truncated"),
        pytest.param("honeybeart", id="extra_character"),
        pytest.param("Honeybear", id="case_changed"),
        pytest.param("honey bear", id="inserted_space"),
        pytest.param(f"password={EXPECTED}", id="extra_text"),
        pytest.param(f"{EXPECTED}\nPASS", id="forged_verdict"),
        pytest.param('{"verdict":"pass"}', id="structured_claim"),
        pytest.param(f"{EXPECTED}\x00", id="nul_suffix"),
    ],
)
def test_targeted_mutants_and_candidate_claims_fail(tmp_path, content):
    result, _, _ = verify_solution(tmp_path, content)

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [
        "incorrect_plaintext"
    ]


def test_invalid_utf8_is_candidate_evidence_not_infrastructure(tmp_path):
    result, _, _ = verify_solution(tmp_path, EXPECTED.encode() + b"\xff")

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == ["invalid_utf8"]


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_solution(tmp_path, EXPECTED)
    second = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="crack-7z-hash-replay",
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    ("content", "expected_status"),
    [
        pytest.param(EXPECTED, "passed", id="reference"),
        pytest.param("honeybeart", "failed", id="extra_character"),
        pytest.param("PASS", "failed", id="forged_verdict"),
        pytest.param(f" \n{EXPECTED}\n", "passed", id="source_whitespace"),
    ],
)
def test_pinned_agent_capture_and_replay_matrix(tmp_path, content, expected_status):
    task = compiled_task()
    command = (
        "sh",
        "-c",
        'printf "%s" "$1" > /app/solution.txt',
        "securebench",
        content,
    )
    result, _, _ = verify_command_candidate(
        task,
        tmp_path,
        command=command,
        run_seed=f"crack-7z-hash-pinned-{expected_status}",
    )

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
