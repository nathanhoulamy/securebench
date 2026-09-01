from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ArtifactCheck
from securebench.verification import VerificationEngine
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_module,
    load_terminal_task,
    verify_command_candidate,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"
TASK_ID = "terminal-bench/extract-moves-from-video"
IMAGE = (
    "alexgshaw/extract-moves-from-video@"
    "sha256:14a9dcca7d08ce53c5a0ed9fbd663a996ef28f207c199ed69d9ccf6064f8b184"
)
ORACLE_ROOT = (
    PACK / "v2" / "hidden" / "extract-moves-from-video" / "oracle"
)
ORACLE = ORACLE_ROOT / "oracle.py"
SOURCE_VERIFIER = (
    PACK
    / "hidden"
    / "extract-moves-from-video"
    / "tests"
    / "test_outputs.py"
)
EXPECTED_SHA256 = "218abc48833a22f05d5655c157c81121cc5edf333059c2c34a65788e1065eceb"
EXPECTED = (ORACLE_ROOT / "solution.txt").read_text(encoding="utf-8")


def compiled_task():
    return load_terminal_task(TASK_ID)


def verify_solution(tmp_path: Path, content: str | bytes):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "downloaded-video.mp4").write_bytes(b"excluded")
    target = workspace / "solution.txt"
    if isinstance(content, str):
        target.write_text(content, encoding="utf-8", newline="")
    else:
        target.write_bytes(content)
    return verify_workspace(
        compiled_task(),
        workspace,
        tmp_path / "store",
        run_seed="extract-moves-from-video-qualification",
    )


def source_accepts(source, content: str) -> bool:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    distance = source.levenshtein_distance(normalized, source.SOLUTION)
    maximum = max(len(normalized), len(source.SOLUTION))
    similarity = 100.0 if maximum == 0 else 100.0 * (1 - distance / maximum)
    return similarity >= 90.0


def test_extract_moves_row_is_passive_bounded_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    assert task.environment.timeout_seconds == 1800
    assert not task.assets
    assert len(task.verification.checks) == 1
    check = task.verification.checks[0]
    assert isinstance(check, ArtifactCheck)
    assert check.id == "solution_artifact"
    assert check.artifacts[0].parser == "securebench.utf8-text/v1"
    assert not task.verification.resources.runtime
    candidate = task.verification.candidate
    assert candidate.max_total_files == 1
    assert candidate.max_total_bytes == 16_384
    assert [(item.id, item.path, item.max_bytes) for item in candidate.files] == [
        ("solution", "/app/solution.txt", 16_384)
    ]
    assert {
        path.relative_to(ORACLE_ROOT).as_posix()
        for path in ORACLE_ROOT.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    } == {"oracle.py", "oracle.yaml", "solution.txt"}


def test_host_transcript_is_exactly_the_source_verifier_solution():
    source = load_module(SOURCE_VERIFIER, "extract_moves_source_solution")

    assert EXPECTED == source.SOLUTION
    assert len(EXPECTED) == 1_346
    assert len(EXPECTED.splitlines()) == 280
    assert EXPECTED.endswith("\n")
    assert hashlib.sha256(EXPECTED.encode()).hexdigest() == EXPECTED_SHA256


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(EXPECTED, id="exact"),
        pytest.param(EXPECTED.replace("\n", "\r\n"), id="universal-newlines"),
        pytest.param(EXPECTED + "x" * 149, id="maximum-passing-append"),
        pytest.param(EXPECTED + "x" * 150, id="minimum-failing-append"),
        pytest.param(EXPECTED[:-134], id="maximum-passing-truncation"),
        pytest.param(EXPECTED[:-135], id="minimum-failing-truncation"),
        pytest.param(EXPECTED.replace("\n", " "), id="lost-line-breaks"),
        pytest.param(EXPECTED.upper(), id="case-changed"),
        pytest.param("\n".join(reversed(EXPECTED.splitlines())) + "\n", id="reordered"),
        pytest.param(EXPECTED + "\x00", id="nul-edit"),
    ],
)
def test_oracle_distance_and_threshold_match_the_source_verifier(content):
    source = load_module(SOURCE_VERIFIER, "extract_moves_source_distance")
    oracle = load_module(ORACLE, "extract_moves_oracle_distance")
    normalized = oracle.universal_newlines(content)

    assert oracle.levenshtein_distance(normalized, EXPECTED) == (
        source.levenshtein_distance(normalized, source.SOLUTION)
    )
    assert oracle.source_threshold_passes(normalized, EXPECTED) is source_accepts(
        source, content
    )


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(EXPECTED, id="exact"),
        pytest.param(EXPECTED.replace("\n", "\r\n"), id="crlf"),
        pytest.param(EXPECTED + "x" * 149, id="append-threshold"),
        pytest.param(EXPECTED[:-134], id="delete-threshold"),
        pytest.param(EXPECTED + "\x00", id="small-nul-edit"),
    ],
)
def test_source_accepted_reference_variants_pass_real_artifact_path(tmp_path, content):
    result, candidate, store = verify_solution(tmp_path, content)

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["solution"]
    assert "downloaded-video.mp4" not in str(manifest.payload)


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(EXPECTED + "x" * 150, id="append-over-threshold"),
        pytest.param(EXPECTED[:-135], id="delete-over-threshold"),
        pytest.param(EXPECTED.replace("\n", " "), id="lost-line-breaks"),
        pytest.param(EXPECTED.upper(), id="case-changed"),
        pytest.param("\n".join(reversed(EXPECTED.splitlines())) + "\n", id="reordered"),
        pytest.param('{"verdict":"pass"}', id="forged-verdict"),
        pytest.param("", id="empty"),
    ],
)
def test_targeted_transcript_mutants_and_claims_fail(tmp_path, content):
    result, _, _ = verify_solution(tmp_path, content)

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [
        "similarity_below_threshold"
    ]


def test_invalid_utf8_is_candidate_evidence_not_infrastructure(tmp_path):
    result, _, _ = verify_solution(tmp_path, EXPECTED.encode() + b"\xff")

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == ["invalid_utf8"]


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_solution(tmp_path, EXPECTED)
    replay = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="extract-moves-from-video-replay",
    )

    assert first.status == replay.status == "passed"
    assert first.candidate_digest == replay.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    ("content", "expected_status"),
    [
        pytest.param(EXPECTED, "passed", id="reference"),
        pytest.param(EXPECTED.replace("\n", "\r\n"), "passed", id="crlf"),
        pytest.param(EXPECTED + "x" * 149, "passed", id="threshold-pass"),
        pytest.param(EXPECTED + "x" * 150, "failed", id="threshold-fail"),
        pytest.param(EXPECTED.replace("\n", " "), "failed", id="line-breaks"),
        pytest.param('{"verdict":"pass"}', "failed", id="forged-verdict"),
    ],
)
def test_pinned_agent_capture_and_replay_matrix(
    tmp_path, content, expected_status
):
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=(
            "sh",
            "-c",
            'printf "%s" "$1" > /app/solution.txt',
            "securebench",
            content,
        ),
        run_seed=f"extract-moves-pinned-{expected_status}",
    )

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
