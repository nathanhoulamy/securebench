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
    target_id: str
    oversized_target: str | None = None
    exact_missing_categories: tuple[str, ...] | None = (
        "candidate_capture_rejected",
    )
    contained_missing_categories: tuple[str, ...] = ()
    missing_check_ids: tuple[str, ...] | None = None
    base_command: tuple[str, ...] | None = None
    missing_seed: str | None = None

    @property
    def row_name(self) -> str:
        return self.task_id.rsplit("/", 1)[-1]

    @property
    def missing_run_seed(self) -> str:
        return self.missing_seed or f"{self.row_name}-missing"


ROWS = (
    RowCaptureContract(
        task_id="terminal-bench/bn-fit-modify",
        target_id="learned_dag",
        oversized_target="final_sample",
        exact_missing_categories=None,
        contained_missing_categories=("final_sample:candidate_capture_rejected",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/cancel-async-tasks",
        target_id="implementation",
        missing_seed="cancel-async-missing",
        exact_missing_categories=None,
        missing_check_ids=("concurrency_behavior", "cancellation_behavior"),
    ),
    RowCaptureContract(
        task_id="terminal-bench/chess-best-move",
        target_id="moves",
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/circuit-fibsqrt",
        target_id="circuit",
        base_command=("sh", "-c", "rm -f /app/gates.txt"),
    ),
    RowCaptureContract(
        task_id="terminal-bench/cobol-modernization",
        target_id="implementation",
        base_command=("sh", "-c", "rm -f /app/program.py"),
    ),
    RowCaptureContract(
        task_id="terminal-bench/code-from-image",
        target_id="output",
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/count-dataset-tokens",
        target_id="answer",
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/crack-7z-hash",
        target_id="solution",
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/db-wal-recovery",
        target_id="recovered",
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/distribution-search",
        target_id="distribution",
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/dna-assembly",
        target_id="primers",
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/dna-insert",
        target_id="primers",
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/extract-elf",
        target_id="extractor",
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/extract-moves-from-video",
        target_id="solution",
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/feal-linear-cryptanalysis",
        target_id="plaintexts",
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/financial-document-processor",
        target_id="invoices",
        exact_missing_categories=("invoices_tree:candidate_capture_rejected",),
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/fix-code-vulnerability",
        target_id="bottle_source",
        oversized_target="vulnerability_report",
        exact_missing_categories=None,
        missing_check_ids=("candidate_artifacts", "header_validation_behavior"),
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/fix-git",
        target_id="about",
        oversized_target="layout",
        exact_missing_categories=None,
        missing_check_ids=("recovered_files_artifact",),
        base_command=None,
    ),
    RowCaptureContract(
        task_id="terminal-bench/gcode-to-text",
        target_id="decoded_text",
        oversized_target=None,
        exact_missing_categories=("candidate_capture_rejected",),
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/git-leak-recovery",
        target_id="repository",
        oversized_target="recovered_secret",
        exact_missing_categories=None,
        missing_check_ids=("git_recovery_artifact",),
        base_command=None,
    ),
    RowCaptureContract(
        task_id="terminal-bench/gpt2-codegolf",
        target_id="implementation",
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/headless-terminal",
        target_id="implementation",
        oversized_target="dependencies",
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/hf-model-inference",
        target_id="model_cache",
        oversized_target="application",
        base_command=("true",),
    ),
    RowCaptureContract(
        task_id="terminal-bench/install-windows-3.11",
        target_id="launcher",
        oversized_target="qemu_runtime",
        base_command=("true",),
    ),
)


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.row_name)
def test_missing_candidate_is_scored_by_the_oracle(row: RowCaptureContract):
    assert_missing_candidate_failure(
        load_terminal_task(row.task_id),
        run_seed=row.missing_run_seed,
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
    target_id = (
        row.oversized_target
        if attack == "oversized" and row.oversized_target is not None
        else row.target_id
    )
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
