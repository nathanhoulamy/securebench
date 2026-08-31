from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import (
    CandidateCaptureError,
    CandidateStore,
    HostWorkspaceFilesystem,
    StoredCandidate,
    capture_file_bundle,
    capture_production,
)
from securebench.harnesses.command import CommandHarnessProducer
from securebench.schemas.benchmark import FileBundleCandidate, RegularFileEntry
from securebench.tasks import BenchmarkTask
from securebench.verification import VerificationEngine
from securebench.workspaces.cleanup import remove_untrusted_tree


ROOT = Path(__file__).resolve().parents[1]
TERMINAL_BENCH_PACK = ROOT / "benchmarks" / "terminal-bench"
DOCKER_INTEGRATION = pytest.mark.skipif(
    os.environ.get("SECUREBENCH_DOCKER_INTEGRATION") != "1",
    reason="set SECUREBENCH_DOCKER_INTEGRATION=1 for pinned-image qualification",
)


def load_terminal_task(task_id: str) -> BenchmarkTask:
    pack = load_benchmark_pack(
        TERMINAL_BENCH_PACK / "manifest-v2.yaml",
        TERMINAL_BENCH_PACK / "tasks-v2.jsonl",
    )
    return next(task for task in compile_benchmark_pack(pack) if task.id == task_id)


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture_workspace(
    task: BenchmarkTask,
    workspace: Path,
    store_root: Path,
) -> tuple[StoredCandidate, CandidateStore]:
    candidate_spec = task.verification.candidate
    assert isinstance(candidate_spec, FileBundleCandidate)
    store = CandidateStore(store_root)
    candidate = capture_file_bundle(
        HostWorkspaceFilesystem(workspace, guest_root="/app"),
        candidate_spec,
        store,
        baseline_digest=task.baseline_digest,
    )
    return candidate, store


def verify_workspace(
    task: BenchmarkTask,
    workspace: Path,
    store_root: Path,
    *,
    run_seed: str,
):
    candidate, store = capture_workspace(task, workspace, store_root)
    result = VerificationEngine().verify(task, candidate, store, run_seed=run_seed)
    return result, candidate, store


def assert_missing_candidate_failure(
    task: BenchmarkTask,
    *,
    run_seed: str,
    exact_categories: tuple[str, ...] | None = None,
    contained_categories: tuple[str, ...] = (),
    check_ids: tuple[str, ...] | None = None,
) -> None:
    result = VerificationEngine().verify_candidate_error(
        task,
        code="candidate_capture_rejected",
        message="Candidate capture was rejected",
        run_seed=run_seed,
    )

    assert result.status == "failed", result
    assert result.infrastructure_error is None, result
    assert all(check.status == "failed" for check in result.checks), result
    if check_ids is not None:
        assert {check.id for check in result.checks} == set(check_ids)
    categories = result.public_diagnostics["failure_categories"]
    if exact_categories is not None:
        assert categories == list(exact_categories)
    for category in contained_categories:
        assert category in categories


def assert_file_bundle_capture_rejected(
    task: BenchmarkTask,
    tmp_path: Path,
    *,
    attack: str,
    target_id: str,
) -> None:
    candidate_spec = task.verification.candidate
    assert isinstance(candidate_spec, FileBundleCandidate)
    entries = {entry.id: entry for entry in candidate_spec.files}
    target_entry = entries[target_id]
    assert isinstance(target_entry, RegularFileEntry)

    workspace = tmp_path / "workspace"
    for entry in candidate_spec.files:
        assert isinstance(entry, RegularFileEntry)
        target = workspace / Path(entry.path).relative_to("/app")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x")

    target = workspace / Path(target_entry.path).relative_to("/app")
    if attack == "symlink":
        target.unlink()
        payload = target.with_name(f"{target.name}.payload")
        payload.write_bytes(b"x")
        target.symlink_to(payload.name)
    elif attack == "directory":
        target.unlink()
        target.mkdir()
    elif attack == "oversized":
        target.write_bytes(b"x" * (target_entry.max_bytes + 1))
    else:
        raise AssertionError(f"unknown malicious candidate attack: {attack}")

    with pytest.raises(CandidateCaptureError):
        capture_workspace(task, workspace, tmp_path / "store")


def assert_base_capture_rejected(
    task: BenchmarkTask,
    tmp_path: Path,
    *,
    command: tuple[str, ...],
) -> None:
    producer = CommandHarnessProducer(
        command=command,
        workspace_root=tmp_path / "workspaces",
    )
    production = producer.produce(task)
    try:
        with pytest.raises(CandidateCaptureError):
            capture_production(task, production, CandidateStore(tmp_path / "store"))
    finally:
        remove_untrusted_tree(production.workspace, image=task.environment.image)
