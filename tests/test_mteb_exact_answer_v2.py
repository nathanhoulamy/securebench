"""Qualification for the two MTEB exact-answer artifact rows.

`mteb-leaderboard` and `mteb-retrieve` have the same verification shape: one
bounded UTF-8 line compared against a host-held expected string. They share this
file so the shared predicate is proven once, with per-row constants pinned
against each source verifier.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from securebench.execution_profiles import validate_executable_task
from securebench.schemas.benchmark import ArtifactCheck, FileBundleCandidate
from securebench.verification import VerificationEngine
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    assert_base_capture_rejected,
    assert_file_bundle_capture_rejected,
    assert_missing_candidate_failure,
    load_terminal_task,
    verify_command_candidate,
    verify_workspace,
)


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"


@dataclass(frozen=True)
class Row:
    name: str
    check_id: str
    expected: str
    image: str
    domains: tuple[str, ...]

    @property
    def task_id(self) -> str:
        return f"terminal-bench/{self.name}"


ROWS = (
    Row(
        name="mteb-leaderboard",
        check_id="leaderboard_answer_artifact",
        expected="GritLM/GritLM-7B",
        image="sha256:d55f499756a84cd4e38c57afcea438b71dcaeca916fa4f5b470978d47c8fcbfe",
        domains=("huggingface.co", "hf.co", "pypi.org", "pythonhosted.org"),
    ),
    Row(
        name="mteb-retrieve",
        check_id="retrieved_document_artifact",
        expected="MTEB: Massive Text Embedding Benchmark",
        image="sha256:48386cadd04e89e693e7d628df3d9b31a3ee0bbdffdea5054d61189e48f4a51a",
        domains=(
            "huggingface.co",
            "hf.co",
            "xethub.hf.co",
            "pypi.org",
            "pythonhosted.org",
        ),
    ),
)
IDS = [row.name for row in ROWS]


def verify_answer(row: Row, tmp_path: Path, content: str | bytes):
    task = load_terminal_task(row.task_id)
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "notes.md").write_text("excluded", encoding="utf-8")
    target = workspace / "result.txt"
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return verify_workspace(
        task, workspace, tmp_path / "store", run_seed=f"{row.name}-test-seed"
    )


def assert_candidate_failure(row: Row, tmp_path: Path, content, category: str):
    result, _, _ = verify_answer(row, tmp_path, content)

    assert result.status == "failed", result
    assert result.score == 0.0
    assert result.infrastructure_error is None, result
    assert category in result.public_diagnostics["failure_categories"], result


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_row_is_bounded_split_and_executable(row: Row):
    task = load_terminal_task(row.task_id)
    validate_executable_task(task)

    assert task.environment.image == row.image
    assert task.environment.workdir == "/app"
    assert task.environment.agent_network.mode == "restricted"
    assert task.environment.agent_network.allowed_domains == row.domains

    candidate = task.verification.candidate
    assert isinstance(candidate, FileBundleCandidate)
    assert [entry.id for entry in candidate.files] == ["answer"]
    assert candidate.files[0].path == "/app/result.txt"

    (check,) = task.verification.checks
    assert isinstance(check, ArtifactCheck)
    assert check.id == row.check_id
    assert check.artifacts[0].parser == "securebench.utf8-text/v1"

    assert task.verification.oracle == "host.task_oracle"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "oracle" not in view
        assert row.expected not in view


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_oracle_expectation_matches_the_source_verifier(row: Row):
    oracle_source = (
        PACK / "v2" / "hidden" / row.name / "oracle" / "oracle.py"
    ).read_text(encoding="utf-8")
    source_verifier = (
        PACK / "hidden" / row.name / "tests" / "test_outputs.py"
    ).read_text(encoding="utf-8")

    assert f'expected = "{row.expected}"' in source_verifier
    assert repr(row.expected) in oracle_source
    # The source requires exactly one line and strips only that line.
    assert "len(lines) == 1" in source_verifier
    assert 'lines[0].strip() == expected' in source_verifier
    assert "invalid_line_count" in oracle_source


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_reviewed_reference_passes(row: Row, tmp_path):
    result, candidate, store = verify_answer(row, tmp_path, row.expected)

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["answer"]
    assert "notes.md" not in json.dumps(manifest.payload)


@pytest.mark.parametrize("row", ROWS, ids=IDS)
@pytest.mark.parametrize(
    "decorate",
    [
        pytest.param(lambda v: v + "\n", id="trailing_newline"),
        pytest.param(lambda v: "  " + v + "  ", id="surrounding_spaces"),
        pytest.param(lambda v: "\t" + v + "\r\n", id="tabs_and_crlf"),
    ],
)
def test_source_strip_behaviour_is_preserved(row: Row, tmp_path, decorate):
    result, _, _ = verify_answer(row, tmp_path, decorate(row.expected))

    assert result.status == "passed", result


@pytest.mark.parametrize("row", ROWS, ids=IDS)
@pytest.mark.parametrize(
    ("mutate", "category"),
    [
        pytest.param(lambda v: v.lower(), "incorrect_answer", id="lowercased"),
        pytest.param(lambda v: v + "x", "incorrect_answer", id="trailing_character"),
        pytest.param(lambda v: v[:-1], "incorrect_answer", id="truncated"),
        pytest.param(lambda v: "", "incorrect_answer", id="empty_file"),
        pytest.param(lambda v: "   ", "incorrect_answer", id="whitespace_only"),
        pytest.param(
            lambda v: f"The answer is {v}", "incorrect_answer", id="prose_wrapped"
        ),
        pytest.param(
            lambda v: f"{v}\nsecond line", "invalid_line_count", id="second_line"
        ),
        pytest.param(
            lambda v: f"\n{v}", "invalid_line_count", id="leading_blank_line"
        ),
        pytest.param(
            lambda v: f"{v}\n\n", "invalid_line_count", id="two_trailing_newlines"
        ),
    ],
)
def test_targeted_semantic_mutants_fail(row: Row, tmp_path, mutate, category):
    assert_candidate_failure(row, tmp_path, mutate(row.expected), category)


@pytest.mark.parametrize("row", ROWS, ids=IDS)
@pytest.mark.parametrize(
    ("content", "category"),
    [
        pytest.param(b"\xff\xfe", "invalid_utf8", id="invalid_utf8"),
        pytest.param(
            b'{"verdict":"pass","score":1.0}', "incorrect_answer", id="forged_verdict"
        ),
    ],
)
def test_malformed_and_forged_artifacts_fail(row: Row, tmp_path, content, category):
    assert_candidate_failure(row, tmp_path, content, category)


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_nul_suffix_is_not_stripped(row: Row, tmp_path):
    assert_candidate_failure(
        row, tmp_path, row.expected.encode() + b"\x00", "incorrect_answer"
    )


@pytest.mark.parametrize("row", ROWS, ids=IDS)
@pytest.mark.parametrize("attack", ["symlink", "directory", "oversized"])
def test_malicious_candidate_filesystem_shapes_are_rejected_at_capture(
    row: Row, tmp_path, attack
):
    assert_file_bundle_capture_rejected(
        load_terminal_task(row.task_id), tmp_path, attack=attack, target_id="answer"
    )


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_missing_deliverable_scores_as_candidate_failure(row: Row):
    assert_missing_candidate_failure(
        load_terminal_task(row.task_id),
        run_seed=f"{row.name}-missing",
        check_ids=(row.check_id,),
    )


@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_stored_candidate_replays_exactly(row: Row, tmp_path):
    first, candidate, store = verify_answer(row, tmp_path, row.expected)
    second = VerificationEngine().verify(
        load_terminal_task(row.task_id),
        candidate,
        store,
        run_seed=f"{row.name}-replay",
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
@pytest.mark.parametrize("row", ROWS, ids=IDS)
def test_base_image_without_deliverable_is_rejected_at_capture(row: Row, tmp_path):
    assert_base_capture_rejected(
        load_terminal_task(row.task_id), tmp_path, command=("true",)
    )


@DOCKER_INTEGRATION
@pytest.mark.parametrize("row", ROWS, ids=IDS)
@pytest.mark.parametrize("correct", [True, False], ids=["reference", "wrong_answer"])
def test_pinned_agent_capture_and_verification(row: Row, tmp_path, correct):
    written = row.expected if correct else "definitely/not-the-answer"
    result, _, _ = verify_command_candidate(
        load_terminal_task(row.task_id),
        tmp_path,
        command=("sh", "-c", f"printf '%s\\n' '{written}' > /app/result.txt"),
        run_seed=f"{row.name}-pinned-{correct}",
    )

    assert result.status == ("passed" if correct else "failed"), result
    assert result.infrastructure_error is None, result
