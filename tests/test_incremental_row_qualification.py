from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests.qualification_support import (
    DOCKER_INTEGRATION,
    assert_base_capture_rejected,
    assert_file_bundle_capture_rejected,
    assert_missing_candidate_failure,
    load_terminal_task,
)


@dataclass(frozen=True)
class RowCaptureContract:
    task_id: str
    missing_seed: str
    shape_target: str
    oversized_target: str
    exact_missing_categories: tuple[str, ...] | None = None
    contained_missing_categories: tuple[str, ...] = ()
    missing_check_ids: tuple[str, ...] | None = None
    base_command: tuple[str, ...] | None = None

    @property
    def row_name(self) -> str:
        return self.task_id.rsplit("/", 1)[-1]


ROWS = (
    RowCaptureContract(
        task_id="terminal-bench/bn-fit-modify",
        missing_seed="bn-fit-modify-missing",
        shape_target="learned_dag",
        oversized_target="final_sample",
        contained_missing_categories=("final_sample:candidate_capture_rejected",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/cancel-async-tasks",
        missing_seed="cancel-async-missing",
        shape_target="implementation",
        oversized_target="implementation",
        missing_check_ids=("concurrency_behavior", "cancellation_behavior"),
    ),
    RowCaptureContract(
        task_id="terminal-bench/chess-best-move",
        missing_seed="chess-best-move-missing",
        shape_target="moves",
        oversized_target="moves",
        exact_missing_categories=("candidate_capture_rejected",),
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/circuit-fibsqrt",
        missing_seed="circuit-fibsqrt-missing",
        shape_target="circuit",
        oversized_target="circuit",
        exact_missing_categories=("candidate_capture_rejected",),
        base_command=("sh", "-c", "rm -f /app/gates.txt"),
    ),
    RowCaptureContract(
        task_id="terminal-bench/cobol-modernization",
        missing_seed="cobol-modernization-missing",
        shape_target="implementation",
        oversized_target="implementation",
        exact_missing_categories=("candidate_capture_rejected",),
        base_command=("sh", "-c", "rm -f /app/program.py"),
    ),
)


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.row_name)
def test_missing_candidate_is_scored_by_the_oracle(row: RowCaptureContract):
    assert_missing_candidate_failure(
        load_terminal_task(row.task_id),
        run_seed=row.missing_seed,
        exact_categories=row.exact_missing_categories,
        contained_categories=row.contained_missing_categories,
        check_ids=row.missing_check_ids,
    )


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.row_name)
@pytest.mark.parametrize("attack", ("symlink", "directory", "oversized"))
def test_file_bundle_capture_rejects_malicious_shapes(
    tmp_path,
    row: RowCaptureContract,
    attack: str,
):
    target_id = row.oversized_target if attack == "oversized" else row.shape_target
    assert_file_bundle_capture_rejected(
        load_terminal_task(row.task_id),
        tmp_path,
        attack=attack,
        target_id=target_id,
    )


BASE_ROWS = tuple(row for row in ROWS if row.base_command is not None)


@DOCKER_INTEGRATION
@pytest.mark.parametrize("row", BASE_ROWS, ids=lambda row: row.row_name)
def test_base_image_fails_stopped_candidate_capture(tmp_path, row: RowCaptureContract):
    assert row.base_command is not None
    assert_base_capture_rejected(
        load_terminal_task(row.task_id),
        tmp_path,
        command=row.base_command,
    )
