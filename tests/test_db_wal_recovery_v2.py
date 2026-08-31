from __future__ import annotations

import hashlib
import json
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
TASK_ID = "terminal-bench/db-wal-recovery"
IMAGE = (
    "alexgshaw/db-wal-recovery@"
    "sha256:0e33ea5ec823975d1bd6c3778395c9f94251dd88f571146057bff6adb7e4594e"
)
MAIN_DB_SHA256 = "68cb288eb29e76d814b4e7ee6887b37c415675e644f88173bc191348e290d119"
ENCRYPTED_WAL_SHA256 = "68753bdce26196a53194260d001544cc6bb8f9f38e2f2f6826d09798e31e6e26"
REFERENCE_ROWS = [
    {"id": 1, "name": "apple", "value": 150},
    {"id": 2, "name": "banana", "value": 250},
    {"id": 3, "name": "cherry", "value": 300},
    {"id": 4, "name": "date", "value": 400},
    {"id": 5, "name": "elderberry", "value": 500},
    {"id": 6, "name": "fig", "value": 600},
    {"id": 7, "name": "grape", "value": 700},
    {"id": 8, "name": "honeydew", "value": 800},
    {"id": 9, "name": "kiwi", "value": 900},
    {"id": 10, "name": "lemon", "value": 1000},
    {"id": 11, "name": "mango", "value": 1100},
]


def compiled_task():
    return load_terminal_task(TASK_ID)


def verify_recovery(tmp_path: Path, content: object | bytes):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "main.db").write_bytes(b"excluded base")
    (workspace / "main.db-wal").write_bytes(b"excluded wal")
    (workspace / "recovery.log").write_text("excluded", encoding="utf-8")
    target = workspace / "recovered.json"
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(json.dumps(content), encoding="utf-8")
    return verify_workspace(
        task,
        workspace,
        tmp_path / "store",
        run_seed="db-wal-recovery-qualification",
    )


def assert_candidate_failure(tmp_path: Path, content: object | bytes, category: str):
    result, _, _ = verify_recovery(tmp_path, content)
    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [category]


def test_db_wal_recovery_row_is_passive_bounded_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert task.environment.workdir == "/app"
    assert len(task.verification.checks) == 1
    check = task.verification.checks[0]
    assert isinstance(check, ArtifactCheck)
    assert check.artifacts[0].parser == "securebench.strict-json/v1"
    assert not task.verification.resources.runtime
    assert task.verification.candidate.max_total_files == 1
    assert task.verification.candidate.max_total_bytes == 65536
    entry = task.verification.candidate.files[0]
    assert entry.id == "recovered"
    assert entry.path == "/app/recovered.json"
    assert entry.kind == "regular_file"
    assert entry.max_bytes == 65536

    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    assert {
        path.relative_to(oracle_root).as_posix()
        for path in oracle_root.rglob("*")
        if path.is_file()
    } == {"oracle.py", "oracle.yaml"}


def test_checked_in_database_inputs_are_stable():
    root = PACK / "docker" / "db-wal-recovery"
    database = (root / "main.db").read_bytes()
    encrypted_wal = (root / "main.db-wal.encrypted").read_bytes()

    assert len(database) == 8192
    assert hashlib.sha256(database).hexdigest() == MAIN_DB_SHA256
    assert len(encrypted_wal) == 16512
    assert hashlib.sha256(encrypted_wal).hexdigest() == ENCRYPTED_WAL_SHA256
    assert bytes(byte ^ 0x42 for byte in encrypted_wal[:4]) == b"\x37\x7f\x06\x82"


def test_reviewed_reference_passes_real_capture_parser_and_oracle(tmp_path):
    result, candidate, store = verify_recovery(tmp_path, REFERENCE_ROWS)

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert manifest.type == "file_bundle"
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["recovered"]
    assert not any(
        name in json.dumps(manifest.payload)
        for name in ("main.db", "main.db-wal", "recovery.log")
    )


def test_source_unscored_fields_and_python_boolean_quirk_are_preserved(tmp_path):
    rows = [dict(row) for row in REFERENCE_ROWS]
    rows[0].update(id=True, name="unchecked", extra="allowed")
    rows[1]["name"] = "also unchecked"
    for row in rows[2:]:
        row["value"] = True

    result, _, _ = verify_recovery(tmp_path, rows)

    assert result.status == "passed", result


@pytest.mark.parametrize(
    ("mutator", "category"),
    [
        pytest.param(lambda rows: rows[:5], "incomplete_recovery", id="base_only"),
        pytest.param(lambda rows: list(reversed(rows)), "records_not_sorted", id="unsorted"),
        pytest.param(
            lambda rows: rows[:1] + [dict(rows[0])] + rows[2:],
            "incomplete_recovery",
            id="duplicate_and_missing_id",
        ),
        pytest.param(
            lambda rows: [{**row, "value": 100} if row["id"] == 1 else row for row in rows],
            "missing_wal_updates",
            id="stale_apple_value",
        ),
        pytest.param(
            lambda rows: [{**row, "value": 200} if row["id"] == 2 else row for row in rows],
            "missing_wal_updates",
            id="stale_banana_value",
        ),
        pytest.param(
            lambda rows: [{**row, "name": "wrong"} if row["id"] == 3 else row for row in rows],
            "incorrect_record_names",
            id="wrong_base_name",
        ),
        pytest.param(
            lambda rows: [{**row, "name": "wrong"} if row["id"] == 6 else row for row in rows],
            "incorrect_record_names",
            id="wrong_wal_name",
        ),
        pytest.param(
            lambda rows: [{**row, "id": "1"} if row["id"] == 1 else row for row in rows],
            "invalid_row_type",
            id="string_id",
        ),
        pytest.param(
            lambda rows: [{**row, "name": 3} if row["id"] == 3 else row for row in rows],
            "invalid_row_type",
            id="integer_name",
        ),
        pytest.param(
            lambda rows: [{**row, "value": 150.0} if row["id"] == 1 else row for row in rows],
            "invalid_row_type",
            id="float_value",
        ),
        pytest.param(
            lambda rows: [{key: value for key, value in row.items() if key != "value"} if row["id"] == 4 else row for row in rows],
            "invalid_row_shape",
            id="missing_required_field",
        ),
    ],
)
def test_targeted_semantic_mutants_fail(tmp_path, mutator, category):
    rows = [dict(row) for row in REFERENCE_ROWS]
    assert_candidate_failure(tmp_path, mutator(rows), category)


@pytest.mark.parametrize(
    ("content", "category"),
    [
        pytest.param({}, "root_not_array", id="top_level_object"),
        pytest.param(b"not json", "invalid_json", id="malformed_json"),
        pytest.param(b'{"verdict":"pass"}', "root_not_array", id="forged_verdict"),
        pytest.param(b'[{"id":1,"id":2,"name":"x","value":150}]', "invalid_json", id="duplicate_key"),
        pytest.param(b"[]\xff", "invalid_utf8", id="invalid_utf8"),
        pytest.param(b"[]\x00", "invalid_json", id="nul_suffix"),
    ],
)
def test_malformed_ambiguous_and_forged_artifacts_fail(tmp_path, content, category):
    assert_candidate_failure(tmp_path, content, category)


def test_stored_candidate_replays_exactly_without_cross_run_state(tmp_path):
    first, candidate, store = verify_recovery(tmp_path, REFERENCE_ROWS)
    second = VerificationEngine().verify(
        compiled_task(),
        candidate,
        store,
        run_seed="db-wal-recovery-replay",
    )

    assert first.status == second.status == "passed"
    assert first.candidate_digest == second.candidate_digest == candidate.digest


@DOCKER_INTEGRATION
@pytest.mark.parametrize(
    ("rows", "expected_status"),
    [
        pytest.param(REFERENCE_ROWS, "passed", id="reference"),
        pytest.param(REFERENCE_ROWS[:5], "failed", id="base_only"),
        pytest.param([{**row, "value": 100} if row["id"] == 1 else row for row in REFERENCE_ROWS], "failed", id="stale_update"),
        pytest.param({"verdict": "pass"}, "failed", id="forged_verdict"),
    ],
)
def test_pinned_agent_capture_and_replay_matrix(tmp_path, rows, expected_status):
    task = compiled_task()
    content = json.dumps(rows, separators=(",", ":"))
    command = (
        "python3",
        "-c",
        "from pathlib import Path; import sys; Path('/app/recovered.json').write_text(sys.argv[1])",
        content,
    )
    result, _, _ = verify_command_candidate(
        task,
        tmp_path,
        command=command,
        run_seed=f"db-wal-recovery-pinned-{expected_status}",
    )

    assert result.status == expected_status, result
    assert result.infrastructure_error is None, result
