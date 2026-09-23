from __future__ import annotations

import json
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
TASK_ID = "terminal-bench/log-summary-date-ranges"
IMAGE = "sha256:e51bda730f415064b19bcf1ab0801adca7569b16f34374d5f5bf79a0ceb7302d"

HEADER = ["period", "severity", "count"]
REFERENCE_ROWS = [
    ["today", "ERROR", "370"],
    ["today", "WARNING", "463"],
    ["today", "INFO", "1433"],
    ["last_7_days", "ERROR", "2969"],
    ["last_7_days", "WARNING", "4020"],
    ["last_7_days", "INFO", "12203"],
    ["last_30_days", "ERROR", "9594"],
    ["last_30_days", "WARNING", "12847"],
    ["last_30_days", "INFO", "38702"],
    ["month_to_date", "ERROR", "4682"],
    ["month_to_date", "WARNING", "6327"],
    ["month_to_date", "INFO", "19420"],
    ["total", "ERROR", "14160"],
    ["total", "WARNING", "18772"],
    ["total", "INFO", "56621"],
]


def compiled_task():
    return load_terminal_task(TASK_ID)


def render(header: list[str], rows: list[list[str]]) -> str:
    return "\n".join(",".join(record) for record in [header, *rows]) + "\n"


def verify_summary(tmp_path: Path, content: str | bytes):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    # Intermediate analysis output is outside the declared candidate.
    (workspace / "counts.tmp").write_text("excluded", encoding="utf-8")
    target = workspace / "summary.csv"
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return verify_workspace(
        task,
        workspace,
        tmp_path / "store",
        run_seed="log-summary-date-ranges-test-seed",
    )


def assert_candidate_failure(tmp_path: Path, content: str | bytes, category: str):
    result, _, _ = verify_summary(tmp_path, content)

    assert result.status == "failed", result
    assert result.score == 0.0
    assert result.infrastructure_error is None, result
    assert category in result.public_diagnostics["failure_categories"], result
    return result


def test_log_summary_row_is_bounded_split_and_executable():
    task = compiled_task()
    validate_executable_task(task)

    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    # The logs ship inside the pinned image, so the task needs no egress.
    assert task.environment.agent_network.mode == "none"

    candidate = task.verification.candidate
    assert isinstance(candidate, FileBundleCandidate)
    assert candidate.max_total_files == 1
    assert [entry.id for entry in candidate.files] == ["summary"]
    assert candidate.files[0].path == "/app/summary.csv"

    (check,) = task.verification.checks
    assert isinstance(check, ArtifactCheck)
    assert check.id == "summary_artifact"
    (artifact,) = check.artifacts
    assert artifact.parser == "securebench.strict-csv/v1"

    assert task.verification.oracle == "host.task_oracle"
    for role in ("agent", "evaluation_runtime"):
        view = str(task.view_for(role))
        assert "oracle" not in view
        assert "56621" not in view


def test_oracle_encodes_exactly_the_source_expected_table():
    oracle_source = (
        PACK / "v2" / "hidden" / "log-summary-date-ranges" / "oracle" / "oracle.py"
    ).read_text(encoding="utf-8")
    source_verifier = (
        PACK / "hidden" / "log-summary-date-ranges" / "tests" / "test_outputs.py"
    ).read_text(encoding="utf-8")

    # Every expected triple must appear in both the source verifier and the Oracle.
    for period, severity, count in REFERENCE_ROWS:
        triple = f'["{period}", "{severity}", "{count}"]'
        assert triple in oracle_source, triple
        assert f'"{period}", "{severity}", "{count}"' in source_verifier, triple


def test_reviewed_reference_passes_real_capture_parser_and_oracle(tmp_path):
    result, candidate, store = verify_summary(
        tmp_path, render(HEADER, REFERENCE_ROWS)
    )

    assert result.status == "passed", result
    assert result.score == 1.0
    assert result.checks[0].id == "summary_artifact"

    manifest = store.load_candidate(candidate.digest)
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["summary"]
    assert "counts.tmp" not in json.dumps(manifest.payload)


@pytest.mark.parametrize(
    ("mutator", "category"),
    [
        pytest.param(
            lambda rows: rows[:-1], "unexpected_row_count", id="missing_row"
        ),
        pytest.param(
            lambda rows: rows + [["total", "DEBUG", "1"]],
            "unexpected_row_count",
            id="extra_row",
        ),
        pytest.param(
            lambda rows: list(reversed(rows)), "incorrect_row", id="reordered"
        ),
        pytest.param(
            lambda rows: [
                ["today", "ERROR", "371"] if r[0] == "today" and r[1] == "ERROR" else r
                for r in rows
            ],
            "incorrect_row",
            id="off_by_one_count",
        ),
        pytest.param(
            lambda rows: [
                ["today", "ERROR", "370.0"]
                if r[0] == "today" and r[1] == "ERROR"
                else r
                for r in rows
            ],
            "incorrect_row",
            id="float_formatted_count",
        ),
        pytest.param(
            lambda rows: [
                ["today", "ERROR", " 370"] if r[0] == "today" and r[1] == "ERROR" else r
                for r in rows
            ],
            "incorrect_row",
            id="padded_count",
        ),
        pytest.param(
            lambda rows: [[r[0], r[1].lower(), r[2]] for r in rows],
            "incorrect_row",
            id="lowercased_severity",
        ),
        pytest.param(
            # The WARNING message text in the logs deliberately contains the word
            # "ERROR"; a naive substring counter inflates ERROR and deflates WARNING.
            lambda rows: [
                ["today", "ERROR", "833"]
                if r == ["today", "ERROR", "370"]
                else (["today", "WARNING", "0"] if r == ["today", "WARNING", "463"] else r)
                for r in rows
            ],
            "incorrect_row",
            id="naive_substring_severity_counter",
        ),
    ],
)
def test_targeted_semantic_mutants_fail(tmp_path, mutator, category):
    rows = [list(record) for record in REFERENCE_ROWS]
    assert_candidate_failure(tmp_path, render(HEADER, mutator(rows)), category)


@pytest.mark.parametrize(
    ("content", "category"),
    [
        pytest.param(
            render(["period", "severity", "total"], REFERENCE_ROWS),
            "unexpected_header",
            id="wrong_header_name",
        ),
        pytest.param(
            render(["severity", "period", "count"], REFERENCE_ROWS),
            "unexpected_header",
            id="reordered_header",
        ),
        pytest.param(b"not,a\nvalid csv row count\n", "invalid_csv_shape", id="ragged_rows"),
        pytest.param(b"\xff\xfe", "invalid_utf8", id="invalid_utf8"),
        pytest.param(b"period,severity,count\n\x00", "invalid_csv", id="nul_byte"),
        pytest.param(
            b'{"verdict":"pass"}', "unexpected_header", id="forged_verdict_object"
        ),
    ],
)
def test_malformed_and_forged_artifacts_fail(tmp_path, content, category):
    assert_candidate_failure(tmp_path, content, category)


@pytest.mark.parametrize("attack", ["symlink", "directory", "oversized"])
def test_malicious_candidate_filesystem_shapes_are_rejected_at_capture(
    tmp_path, attack
):
    assert_file_bundle_capture_rejected(
        compiled_task(), tmp_path, attack=attack, target_id="summary"
    )


def test_missing_deliverable_scores_as_candidate_failure():
    assert_missing_candidate_failure(
        compiled_task(),
        run_seed="log-summary-date-ranges-missing",
        check_ids=("summary_artifact",),
    )


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_summary(tmp_path, render(HEADER, REFERENCE_ROWS))
    second = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="log-summary-date-ranges-replay",
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
def test_base_image_without_deliverable_is_rejected_at_capture(tmp_path):
    assert_base_capture_rejected(compiled_task(), tmp_path, command=("true",))


@DOCKER_INTEGRATION
def test_pinned_image_ships_the_public_log_corpus(tmp_path):
    """The 164 deterministic log files must be present for the task to be solvable."""
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=(
            "sh",
            "-c",
            "printf 'period,severity,count\\n' > /app/summary.csv; "
            "ls /app/logs | wc -l >> /app/summary.csv",
        ),
        run_seed="log-summary-date-ranges-corpus",
    )

    # Scoring fails (the file is not a real summary), but the command ran and
    # the corpus existed; what must not happen is an infrastructure error.
    assert result.status == "failed", result
    assert result.infrastructure_error is None, result


@DOCKER_INTEGRATION
def test_pinned_agent_capture_and_verification(tmp_path):
    payload = render(HEADER, REFERENCE_ROWS)
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=("sh", "-c", f"printf '%s' '{payload}' > /app/summary.csv"),
        run_seed="log-summary-date-ranges-pinned",
    )

    assert result.status == "passed", result
    assert result.infrastructure_error is None, result
