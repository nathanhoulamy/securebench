from __future__ import annotations

from pathlib import Path

import pytest

from securebench.candidates import (
    CandidateStore,
    capture_production,
)
from securebench.execution_profiles import validate_executable_task
from securebench.harnesses.command import CommandHarnessProducer
from securebench.schemas.benchmark import ArtifactCheck
from securebench.verification import VerificationEngine
from securebench.workspaces.cleanup import remove_untrusted_tree
from tests.qualification_support import (
    DOCKER_INTEGRATION,
    load_terminal_task,
    verify_workspace,
)


TASK_ID = "terminal-bench/chess-best-move"
IMAGE = (
    "alexgshaw/chess-best-move@"
    "sha256:bb447f94d9e2a8ed879f85c85a514b213b7418f9fe11fd7b2428a0b0e436e647"
)


def compiled_task():
    return load_terminal_task(TASK_ID)


def verify_moves(tmp_path: Path, content: str | bytes):
    task = compiled_task()
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    target = workspace / "move.txt"
    if isinstance(content, str):
        target.write_text(content, encoding="utf-8")
    else:
        target.write_bytes(content)
    return verify_workspace(
        task,
        workspace,
        tmp_path / "store",
        run_seed="chess-best-move-qualification",
    )


def test_chess_row_is_passive_bounded_and_executable():
    task = compiled_task()

    validate_executable_task(task)
    assert task.environment.image == IMAGE
    assert len(task.verification.checks) == 1
    assert isinstance(task.verification.checks[0], ArtifactCheck)
    assert not task.verification.resources.runtime
    assert task.verification.candidate.max_total_files == 1
    assert task.verification.candidate.max_total_bytes == 4096
    assert task.verification.candidate.files[0].path == "/app/move.txt"

    oracle_root = Path(task.resources.resources["host.task_oracle"].value["source_path"])
    assert {
        path.relative_to(oracle_root).as_posix()
        for path in oracle_root.rglob("*")
        if path.is_file()
    } == {"oracle.py", "oracle.yaml"}


@pytest.mark.parametrize("content", ["g2g4\ne2e4\n", " e2e4\t g2g4 "])
def test_chess_reference_move_set_passes_in_any_order_and_whitespace(tmp_path, content):
    result, candidate, store = verify_moves(tmp_path, content)

    assert result.status == "passed", result
    assert result.score == 1.0
    manifest = store.load_candidate(candidate.digest)
    assert [entry["id"] for entry in manifest.payload["entries"]] == ["moves"]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("e2e4", id="missing_move"),
        pytest.param("e2e4 g2g4 a2a4", id="extra_move"),
        pytest.param("e2e4 e2e4", id="duplicate_move"),
        pytest.param("e2e4 g2g3", id="wrong_move"),
        pytest.param("E2E4 g2g4", id="case_changed"),
        pytest.param("e2e4 g2g4 PASS", id="forged_verdict"),
    ],
)
def test_chess_targeted_mutants_and_claims_fail(tmp_path, content):
    result, _, _ = verify_moves(tmp_path, content)

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == [
        "incorrect_move_set"
    ]


def test_chess_invalid_utf8_is_candidate_evidence_not_infrastructure(tmp_path):
    result, _, _ = verify_moves(tmp_path, b"e2e4\ng2g4\n\xff")

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert result.public_diagnostics["failure_categories"] == ["invalid_utf8"]


@DOCKER_INTEGRATION
def test_chess_reference_passes_pinned_agent_capture_and_replay(tmp_path):
    task = compiled_task()
    script = (
        "from pathlib import Path;"
        "image=Path('/app/chess_board.png').read_bytes();"
        "assert len(image)==37022 and image.startswith(b'\\x89PNG\\r\\n\\x1a\\n');"
        "Path('/app/move.txt').write_text('g2g4\\ne2e4\\n',encoding='utf-8')"
    )
    producer = CommandHarnessProducer(
        command=("python3", "-c", script),
        workspace_root=tmp_path / "workspaces",
    )
    production = producer.produce(task)
    try:
        store = CandidateStore(tmp_path / "store")
        candidate = capture_production(task, production, store)
        result = VerificationEngine().verify(
            task,
            candidate,
            store,
            run_seed="chess-best-move-pinned-reference",
        )
    finally:
        remove_untrusted_tree(production.workspace, image=task.environment.image)

    assert result.status == "passed", result
