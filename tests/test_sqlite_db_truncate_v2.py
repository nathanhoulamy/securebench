from __future__ import annotations

import hashlib
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
TASK_ID = "terminal-bench/sqlite-db-truncate"
IMAGE = (
    "alexgshaw/sqlite-db-truncate@"
    "sha256:aabac93c93bd1f310e6a6fb893911d7735026ed18491c72133c9196a09092ca4"
)
TRUNCATED_DB_SHA256 = (
    "a7f00ee232fe621629dc014eb2619ac793131843ede1fd892f3b8b7e17332a5b"
)

# The full recoverable row set, matching the pinned source verifier's `soln`
# list at benchmarks/terminal-bench/hidden/sqlite-db-truncate/tests/test_outputs.py.
REFERENCE_ROWS = [
    {"word": "testword02", "value": 10.0},
    {"word": "testword03", "value": 25.0},
    {"word": "testword04", "value": 42.0},
    {"word": "testword05", "value": 50.0},
    {"word": "testword06", "value": 75.0},
    {"word": "testword07", "value": 99.0},
    {"word": "testword08", "value": 99.99},
    {"word": "testword09", "value": 0.5},
]
# The source asserts `score > 6` over a set intersection, i.e. at least seven
# distinct correct (word, value) pairs.
SOURCE_MINIMUM = 7


def compiled_task():
    return load_terminal_task(TASK_ID)


def verify_recovery(tmp_path: Path, content: object | bytes):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    # Candidate-side copies of the public input and of scratch work are
    # deliberately outside the declared candidate and must not be captured.
    (workspace / "trunc.db").write_bytes(b"candidate-modified")
    (workspace / "scratch.log").write_text("excluded", encoding="utf-8")
    target = workspace / "recover.json"
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(json.dumps(content), encoding="utf-8")
    return verify_workspace(
        task,
        workspace,
        tmp_path / "store",
        run_seed="sqlite-db-truncate-test-seed",
    )


def assert_candidate_failure(tmp_path: Path, content: object | bytes, category: str):
    result, _, _ = verify_recovery(tmp_path, content)

    assert result.status == "failed", result
    assert result.score == 0.0
    assert result.infrastructure_error is None, result
    assert category in result.public_diagnostics["failure_categories"], result
    return result


def test_sqlite_row_is_bounded_split_and_executable():
    task = compiled_task()
    validate_executable_task(task)

    assert task.environment.image == IMAGE
    assert "@sha256:" in task.environment.image
    assert task.environment.agent_network.mode == "internet"
    assert task.environment.agent_network.allowed_domains == ()

    candidate = task.verification.candidate
    assert isinstance(candidate, FileBundleCandidate)
    assert candidate.max_total_files == 1
    assert [entry.id for entry in candidate.files] == ["recovery"]
    assert candidate.files[0].path == "/app/recover.json"
    assert candidate.files[0].max_bytes == 65536

    (check,) = task.verification.checks
    assert isinstance(check, ArtifactCheck)
    assert check.id == "recovery_artifact"
    (artifact,) = check.artifacts
    assert artifact.parser == "securebench.strict-json/v1"
    assert artifact.limits.max_bytes == 65536

    # The Oracle is host-only and never reachable from either environment.
    assert task.verification.oracle == "host.task_oracle"
    for role in ("agent", "evaluation_runtime"):
        assert "oracle" not in str(task.view_for(role))


def test_public_input_and_source_constants_are_stable():
    database = (PACK / "docker" / "sqlite-db-truncate" / "trunc.db").read_bytes()

    assert len(database) == 4096
    assert hashlib.sha256(database).hexdigest() == TRUNCATED_DB_SHA256
    # The fixture is a truncated fragment, so the SQLite file header is gone and
    # the bytes begin mid-database with a B-tree leaf page (0x0d). Recovery must
    # therefore parse raw pages rather than open the file as a database.
    assert database[:1] == b"\x0d"
    assert b"SQLite format 3" not in database

    # The host Oracle must encode exactly the pinned source expectations.
    oracle_source = (
        PACK / "v2" / "hidden" / "sqlite-db-truncate" / "oracle" / "oracle.py"
    ).read_text(encoding="utf-8")
    for row in REFERENCE_ROWS:
        assert f'("{row["word"]}", {row["value"]})' in oracle_source
    assert f"MINIMUM_RECOVERED = {SOURCE_MINIMUM}" in oracle_source


def test_reviewed_reference_passes_real_capture_parser_and_oracle(tmp_path):
    result, candidate, store = verify_recovery(tmp_path, REFERENCE_ROWS)

    assert result.status == "passed", result
    assert result.score == 1.0
    assert result.checks[0].id == "recovery_artifact"

    manifest = store.load_candidate(candidate.digest)
    assert manifest.type == "file_bundle"
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["recovery"]
    payload = json.dumps(manifest.payload)
    assert "trunc.db" not in payload
    assert "scratch.log" not in payload


def test_exact_source_threshold_boundary_is_preserved(tmp_path):
    """Seven correct pairs pass, six fail — the source's `score > 6` boundary."""
    seven, _, _ = verify_recovery(tmp_path / "seven", REFERENCE_ROWS[:SOURCE_MINIMUM])
    assert seven.status == "passed", seven

    assert_candidate_failure(
        tmp_path / "six",
        REFERENCE_ROWS[: SOURCE_MINIMUM - 1],
        "insufficient_recovery",
    )


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        pytest.param(
            REFERENCE_ROWS + [{"word": "testword99", "value": 1.0}],
            "extra rows are unscored by the source set intersection",
            id="extra_unscored_row",
        ),
        pytest.param(
            [{**row, "note": "ignored"} for row in REFERENCE_ROWS],
            "unknown keys are ignored by the source",
            id="extra_keys",
        ),
        pytest.param(
            list(reversed(REFERENCE_ROWS)),
            "the source compares sets, so row order is unscored",
            id="reordered",
        ),
        pytest.param(
            [{"word": "testword02", "value": 10}] + REFERENCE_ROWS[1:],
            "JSON 10 equals 10.0 under the source's float comparison",
            id="integer_valued_float",
        ),
    ],
)
def test_source_unscored_quirks_are_preserved(tmp_path, rows, reason):
    result, _, _ = verify_recovery(tmp_path, rows)

    assert result.status == "passed", f"{reason}: {result}"


def test_duplicate_rows_cannot_inflate_recovery(tmp_path):
    """Repeating one correct pair must not reach the threshold."""
    inflated = [dict(REFERENCE_ROWS[0]) for _ in range(20)]

    assert_candidate_failure(tmp_path, inflated, "insufficient_recovery")


@pytest.mark.parametrize(
    ("mutator", "category"),
    [
        pytest.param(
            lambda rows: rows[:6],
            "insufficient_recovery",
            id="below_threshold",
        ),
        pytest.param(
            lambda rows: [{**row, "value": row["value"] + 1} for row in rows],
            "insufficient_recovery",
            id="all_values_shifted",
        ),
        pytest.param(
            lambda rows: [{**row, "value": 99.9} if row["word"] == "testword08" else row for row in rows][:7],
            "insufficient_recovery",
            id="rounded_precision_loss",
        ),
        pytest.param(
            lambda rows: [{**row, "word": row["word"].upper()} for row in rows],
            "insufficient_recovery",
            id="case_mutated_words",
        ),
        pytest.param(
            # The source verifier's set comprehension never inspects types:
            # a stringified value simply fails to equal its float
            # counterpart, so it is silently unscored rather than
            # disqualifying. With every row stringified, nothing matches and
            # the candidate falls below the recovery threshold.
            lambda rows: [{**row, "value": str(row["value"])} for row in rows],
            "insufficient_recovery",
            id="stringified_values",
        ),
        pytest.param(
            # Likewise, upstream happily builds ``(word, True)`` tuples; they
            # just do not equal any expected ``(word, float)`` pair here.
            lambda rows: [{**row, "value": True} for row in rows],
            "insufficient_recovery",
            id="boolean_values",
        ),
        pytest.param(
            lambda rows: [{"word": row["word"]} for row in rows],
            "invalid_row_shape",
            id="missing_value_field",
        ),
        pytest.param(
            lambda rows: [[row["word"], row["value"]] for row in rows],
            "invalid_row_shape",
            id="rows_as_arrays",
        ),
        pytest.param(
            # An unhashable ``value`` (a list/object) would blow up
            # upstream's own ``{(item["word"], item["value"]) ...}`` set
            # comprehension with a ``TypeError``; the Oracle mirrors that
            # crash as a whole-candidate failure rather than silently
            # dropping just this row.
            lambda rows: [{**row, "value": [row["value"]]} for row in rows],
            "invalid_row_shape",
            id="unhashable_values",
        ),
    ],
)
def test_targeted_semantic_mutants_fail(tmp_path, mutator, category):
    rows = [dict(row) for row in REFERENCE_ROWS]
    assert_candidate_failure(tmp_path, mutator(rows), category)


def test_type_mismatched_row_is_skipped_like_upstream_and_still_passes(tmp_path):
    """Upstream never disqualifies a candidate for one badly-typed row.

    The source verifier only intersects ``(word, value)`` tuples; a row that
    cannot match anything (wrong type, extra field, or a value the recovery
    process could not coerce) is simply absent from the intersection. Seven
    correct rows plus one type-mismatched row therefore still passes
    upstream (7 matches, over the ``score > 6`` threshold), and must still
    pass here after the fix.
    """
    rows = [dict(row) for row in REFERENCE_ROWS] + [
        {"word": "testword10", "value": "not-a-number"}
    ]

    result, _, _ = verify_recovery(tmp_path, rows)

    assert result.status == "passed", result


@pytest.mark.parametrize(
    ("content", "category"),
    [
        pytest.param({}, "root_not_array", id="top_level_object"),
        pytest.param(b"not json", "invalid_json", id="malformed_json"),
        pytest.param(
            b'{"verdict":"pass","score":1.0}', "root_not_array", id="forged_verdict"
        ),
        pytest.param(
            b'[{"word":"testword02","word":"testword03","value":10.0}]',
            "invalid_json",
            id="duplicate_key",
        ),
        pytest.param(b"[]\xff", "invalid_utf8", id="invalid_utf8"),
        pytest.param(b"[]\x00", "invalid_json", id="nul_suffix"),
        pytest.param(
            json.dumps([{"word": "testword02", "value": float("1e400")}]).encode(),
            "invalid_json",
            id="infinity_literal",
        ),
    ],
)
def test_malformed_ambiguous_and_forged_artifacts_fail(tmp_path, content, category):
    assert_candidate_failure(tmp_path, content, category)


@pytest.mark.parametrize("attack", ["symlink", "directory", "oversized"])
def test_malicious_candidate_filesystem_shapes_are_rejected_at_capture(
    tmp_path, attack
):
    """Oversize, symlink, and directory substitution fail closed during capture.

    These never reach the parser or the Oracle: capture rejects them, so the
    hostile bytes are never read.
    """
    assert_file_bundle_capture_rejected(
        compiled_task(),
        tmp_path,
        attack=attack,
        target_id="recovery",
    )


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_recovery(tmp_path, REFERENCE_ROWS)
    second = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="sqlite-db-truncate-replay",
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest
    assert store.reference(candidate.digest) == candidate


@DOCKER_INTEGRATION
def test_base_image_without_deliverable_is_rejected_at_capture(tmp_path):
    """Gate 1: the untouched base image produces no candidate at all.

    The deliverable does not exist in the pinned image, so capture fails closed
    before any parser or Oracle runs.
    """
    assert_base_capture_rejected(
        compiled_task(),
        tmp_path,
        command=("true",),
    )


def test_missing_deliverable_scores_as_candidate_failure():
    """Gate 1, host side: a rejected capture still yields a failed verdict."""
    assert_missing_candidate_failure(
        compiled_task(),
        run_seed="sqlite-db-truncate-missing",
        check_ids=("recovery_artifact",),
    )


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    ("rows", "expected_status"),
    [
        pytest.param(REFERENCE_ROWS, "passed", id="reference"),
        pytest.param(REFERENCE_ROWS[:6], "failed", id="below_threshold"),
    ],
)
def test_pinned_agent_capture_and_verification(tmp_path, rows, expected_status):
    payload = json.dumps(rows).replace("'", "'\\''")
    result, _, _ = verify_command_candidate(
        compiled_task(),
        tmp_path,
        command=("sh", "-c", f"printf '%s' '{payload}' > /app/recover.json"),
        run_seed=f"sqlite-db-truncate-pinned-{expected_status}",
    )

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
