"""End-to-end execution of strict split-verification benchmark rows."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import (
    CandidateCaptureError,
    CandidateProductionError,
    CandidateProductionTimeout,
    CandidateStore,
    capture_production,
)
from securebench.errors import ConfigError
from securebench.execution_profiles import validate_executable_task
from securebench.harnesses import build_harness_producer
from securebench.harnesses.shared import environment_image_for_task, workspace_dir_name
from securebench.progress import ProgressReporter, emit_progress, progress_context
from securebench.tasks import BenchmarkTask
from securebench.tester_config import TesterConfig
from securebench.verification import ArtifactVerificationEngine
from securebench.verification.models import RESULT_SCHEMA_VERSION


DEFAULT_RESULTS_FILENAME = "results.jsonl"


@dataclass(frozen=True)
class TesterRunSummary:
    run_id: str
    output_dir: str
    output_path: str
    total: int
    verified: int = 0
    passed: int = 0
    score_sum: float = 0.0
    infrastructure_errors: int = 0
    images_pruned: int = 0
    image_prune_failures: int = 0

    @property
    def verification_status(self) -> str:
        return "complete" if self.verified == self.total else "partial"


@dataclass(frozen=True)
class _CompletedTask:
    task: BenchmarkTask
    record: dict[str, Any]


def run_tester_config(
    config: TesterConfig,
    *,
    limit: int | None = None,
    progress: ProgressReporter | None = None,
    resume: bool = False,
) -> TesterRunSummary:
    """Produce, capture, and verify every selected row through the v2 path."""
    output_dir = config.run.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / DEFAULT_RESULTS_FILENAME
    workspace_root = output_dir / "workspaces"
    store = CandidateStore(output_dir / "artifacts")

    pack = load_benchmark_pack(config.benchmark.manifest, config.benchmark.tasks)
    tasks = list(compile_benchmark_pack(pack, limit=limit))
    for task in tasks:
        validate_executable_task(task)
    producer = build_harness_producer(config.harness, workspace_root=workspace_root)

    existing = _resume_records(output_path, config.run.id, tasks, store) if resume else []
    completed_ids = {record["task_id"] for record in existing}
    remaining = [task for task in tasks if task.id not in completed_ids]
    indexes = {task.id: index for index, task in enumerate(tasks, start=1)}
    counters = _summary_counters(existing)
    image_pruner = DockerImageBatchPruner(config.docker.max_cached_images)
    remaining_image_uses = Counter(environment_image_for_task(task) for task in remaining)

    _initialize_results_file(output_path, existing)
    with progress_context(progress):
        emit_progress(
            "run_start",
            run_id=config.run.id,
            output_dir=output_dir,
            max_workers=config.run.max_workers,
        )
        if existing:
            emit_progress("resume", completed=len(existing), remaining=len(remaining), output_path=output_path)
        with output_path.open("a", encoding="utf-8") as output_file:
            def persist(completed: _CompletedTask) -> None:
                output_file.write(_encode_record(completed.record))
                output_file.flush()
                os.fsync(output_file.fileno())
                _add_record(counters, completed.record)
                image = environment_image_for_task(completed.task)
                remaining_image_uses[image] -= 1
                if remaining_image_uses[image] == 0:
                    image_pruner.observe(image)

            if config.run.max_workers == 1:
                for task in remaining:
                    persist(
                        _execute_task(
                            config,
                            task,
                            producer=producer,
                            store=store,
                            workspace_root=workspace_root,
                            progress=progress,
                            index=indexes[task.id],
                            total=len(tasks),
                        )
                    )
            elif remaining:
                worker_count = min(config.run.max_workers, len(remaining))
                with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="securebench-row") as executor:
                    futures = [
                        executor.submit(
                            _execute_task,
                            config,
                            task,
                            producer=producer,
                            store=store,
                            workspace_root=workspace_root,
                            progress=progress,
                            index=indexes[task.id],
                            total=len(tasks),
                        )
                        for task in remaining
                    ]
                    for future in as_completed(futures):
                        persist(future.result())

    return TesterRunSummary(
        run_id=config.run.id,
        output_dir=str(output_dir),
        output_path=str(output_path),
        total=counters["total"],
        verified=counters["verified"],
        passed=counters["passed"],
        score_sum=counters["score_sum"],
        infrastructure_errors=counters["infrastructure_errors"],
        images_pruned=image_pruner.images_pruned,
        image_prune_failures=image_pruner.failures,
    )


def _execute_task(
    config: TesterConfig,
    task: BenchmarkTask,
    *,
    producer: Any,
    store: CandidateStore,
    workspace_root: Path,
    progress: ProgressReporter | None,
    index: int,
    total: int,
) -> _CompletedTask:
    with progress_context(progress):
        emit_progress("task_start", index=index, total=total, task_id=task.id, family=task.family)
        engine = ArtifactVerificationEngine()
        run_seed = f"{config.run.id}:{task.id}"
        try:
            emit_progress("producer_start", task_id=task.id)
            _reset_task_workspace(workspace_root, task)
            try:
                production = producer.produce(task)
            except (CandidateProductionTimeout, CandidateProductionError) as exc:
                code = (
                    "producer_timeout"
                    if isinstance(exc, CandidateProductionTimeout)
                    else "producer_failed"
                )
                emit_progress("producer_done", task_id=task.id, candidate_type="none", status="failed")
                result = engine.verify_candidate_error(
                    task,
                    code=code,
                    message=(
                        "Agent candidate production timed out"
                        if code == "producer_timeout"
                        else "Agent candidate production failed"
                    ),
                    run_seed=run_seed,
                )
            else:
                emit_progress(
                    "producer_done",
                    task_id=task.id,
                    candidate_type=task.verification.candidate.type,
                )
                emit_progress("candidate_capture_start", task_id=task.id)
                try:
                    candidate = capture_production(task, production, store)
                except CandidateCaptureError:
                    emit_progress("candidate_capture_done", task_id=task.id, status="rejected")
                    result = engine.verify_candidate_error(
                        task,
                        code="candidate_capture_rejected",
                        message="Candidate capture was rejected",
                        run_seed=run_seed,
                    )
                else:
                    emit_progress(
                        "candidate_capture_done",
                        task_id=task.id,
                        status="captured",
                        candidate_digest=candidate.digest,
                    )
                    emit_progress("verification_start", task_id=task.id)
                    result = engine.verify(task, candidate, store, run_seed=run_seed)
        except Exception as exc:
            emit_progress(
                "task_internal_error",
                task_id=task.id,
                error_type=type(exc).__name__,
            )
            result = engine.infrastructure_error(
                task,
                code="task_execution_internal_error",
                message=f"Trusted row execution failed: {type(exc).__name__}",
            )
        try:
            _reset_task_workspace(workspace_root, task)
        except Exception as exc:
            emit_progress(
                "task_cleanup_failed",
                task_id=task.id,
                error_type=type(exc).__name__,
            )
            result = engine.infrastructure_error(
                task,
                code="task_workspace_cleanup_failed",
                message=f"Failed to remove untrusted row workspace: {type(exc).__name__}",
            )
        emit_progress(
            "verification_done",
            task_id=task.id,
            status=result.status,
            score=result.score,
        )
        record = result.to_record(run_id=config.run.id)
        emit_progress("task_done", task_id=task.id, status=result.status, passed=result.passed, score=result.score)
        return _CompletedTask(task=task, record=record)


def _reset_task_workspace(workspace_root: Path, task: BenchmarkTask) -> None:
    task_workspace = (workspace_root / workspace_dir_name(task)).resolve()
    root = workspace_root.resolve()
    if not task_workspace.is_relative_to(root):
        raise ValueError(f"task workspace escapes workspace root: {task_workspace}")
    if task_workspace.exists():
        try:
            shutil.rmtree(task_workspace)
        except PermissionError:
            _restore_workspace_permissions(task_workspace, task.environment.image)
            shutil.rmtree(task_workspace)


def _restore_workspace_permissions(workspace: Path, image: str) -> None:
    """Use the pinned row image to make a hostile bind mount removable."""
    container = f"securebench-cleanup-{uuid.uuid4().hex}"
    command = [
        "docker",
        "run",
        "--name",
        container,
        "--entrypoint",
        "",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "DAC_OVERRIDE",
        "--cap-add",
        "FOWNER",
        "--security-opt",
        "no-new-privileges:true",
        "--memory",
        "128m",
        "--pids-limit",
        "32",
        "--mount",
        f"type=bind,source={workspace},target=/securebench-cleanup",
        image,
        "chmod",
        "-R",
        "a+rwX",
        "--",
        "/securebench-cleanup",
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode != 0:
            raise RuntimeError("failed to restore untrusted workspace permissions")
    finally:
        removed = subprocess.run(
            ["docker", "rm", "-f", container],
            check=False,
            capture_output=True,
            text=True,
        )
        if removed.returncode != 0 and "No such container" not in removed.stderr:
            raise RuntimeError("failed to remove workspace cleanup container")


def _resume_records(
    output_path: Path,
    run_id: str,
    tasks: list[BenchmarkTask],
    store: CandidateStore,
) -> list[dict[str, Any]]:
    if not output_path.exists():
        return []
    expected = {task.id: _expected_provenance(task) for task in tasks}
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in output_path.read_text(errors="ignore").splitlines():
        line = line.strip("\x00").strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("run_id") != run_id:
            continue
        task_id = record.get("task_id")
        provenance = record.get("provenance")
        if (
            not isinstance(task_id, str)
            or task_id in seen
            or task_id not in expected
            or not _valid_resume_record(record, expected[task_id])
            or not _resume_candidate_available(record, expected[task_id], store)
        ):
            continue
        seen.add(task_id)
        records.append(record)
    return records


def _resume_candidate_available(
    record: dict[str, Any],
    expected: dict[str, str],
    store: CandidateStore,
) -> bool:
    candidate = record["candidate"]
    digest = candidate["digest"]
    if digest is None:
        return True
    try:
        manifest = store.load_candidate(digest)
        if (
            manifest.type != candidate["type"]
            or manifest.baseline_digest != expected["baseline_digest"]
        ):
            return False
        if manifest.type == "file_bundle":
            entries = manifest.payload.get("entries")
            if not isinstance(entries, list):
                return False
            for entry in entries:
                if not isinstance(entry, dict):
                    return False
                if entry.get("kind") == "regular_file":
                    if not _resume_blob_available(entry, store):
                        return False
                elif entry.get("kind") == "directory_tree":
                    nodes = entry.get("nodes")
                    if not isinstance(nodes, list) or any(
                        not isinstance(node, dict)
                        or node.get("kind") not in {"directory", "regular_file", "symlink"}
                        or (
                            node.get("kind") == "regular_file"
                            and not _resume_blob_available(node, store)
                        )
                        for node in nodes
                    ):
                        return False
                else:
                    return False
        elif manifest.type == "git_patch":
            if not _resume_blob_available(
                {
                    "blob": manifest.payload.get("patch_blob"),
                    "size": manifest.payload.get("patch_bytes"),
                },
                store,
            ):
                return False
        else:
            return False
    except (OSError, ValueError):
        return False
    return True


def _resume_blob_available(value: dict[str, Any], store: CandidateStore) -> bool:
    digest = value.get("blob")
    size = value.get("size")
    if not isinstance(digest, str) or not isinstance(size, int) or size < 0:
        return False
    store.read_blob(digest, expected_size=size)
    return True


def _valid_resume_record(record: dict[str, Any], expected: dict[str, str]) -> bool:
    status = record.get("status")
    passed = record.get("passed")
    score = record.get("score")
    candidate = record.get("candidate")
    provenance = record.get("provenance")
    infrastructure_error = record.get("infrastructure_error")
    expected_fields = {
        "schema_version",
        "run_id",
        "task_id",
        "benchmark_id",
        "status",
        "passed",
        "score",
        "candidate",
        "execution_profile",
        "provenance",
        "checks",
        "public_diagnostics",
    }
    if status == "infrastructure_error":
        expected_fields.add("infrastructure_error")
    return (
        set(record) == expected_fields
        and record.get("schema_version") == RESULT_SCHEMA_VERSION
        and record.get("benchmark_id") == expected["benchmark_id"]
        and record.get("execution_profile") == expected["execution_profile"]
        and status in {"passed", "failed", "infrastructure_error"}
        and isinstance(passed, bool)
        and passed is (status == "passed")
        and isinstance(score, (int, float))
        and not isinstance(score, bool)
        and 0.0 <= float(score) <= 1.0
        and isinstance(candidate, dict)
        and set(candidate) == {"type", "digest"}
        and _valid_candidate_reference(candidate)
        and isinstance(provenance, dict)
        and provenance == {
            key: value
            for key, value in expected.items()
            if key not in {"benchmark_id", "execution_profile"}
        }
        and _valid_check_records(record.get("checks"))
        and _valid_json_object(record.get("public_diagnostics"))
        and (
            isinstance(infrastructure_error, dict)
            and set(infrastructure_error) == {"code", "message"}
            and all(isinstance(value, str) and value for value in infrastructure_error.values())
            if status == "infrastructure_error"
            else infrastructure_error is None
        )
    )


def _valid_check_records(value: object) -> bool:
    if not isinstance(value, list):
        return False
    identifiers: set[str] = set()
    for check in value:
        if not isinstance(check, dict) or set(check) != {
            "id",
            "type",
            "status",
            "cases",
            "evidence_digests",
        }:
            return False
        identifier = check.get("id")
        cases = check.get("cases")
        evidence = check.get("evidence_digests")
        if (
            not isinstance(identifier, str)
            or not identifier
            or identifier in identifiers
            or not isinstance(check.get("type"), str)
            or not check["type"]
            or check.get("status") not in {"passed", "failed", "infrastructure_error"}
            or isinstance(cases, bool)
            or not isinstance(cases, int)
            or cases < 0
            or not isinstance(evidence, list)
            or not all(_is_digest(item) for item in evidence)
        ):
            return False
        identifiers.add(identifier)
    return True


def _valid_json_object(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        json.dumps(value, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        return False
    return True


def _valid_candidate_reference(candidate: dict[str, Any]) -> bool:
    candidate_type = candidate.get("type")
    digest = candidate.get("digest")
    if candidate_type is None or digest is None:
        return candidate_type is None and digest is None
    return candidate_type in {"file_bundle", "git_patch", "filesystem_overlay"} and _is_digest(digest)


def _expected_provenance(task: BenchmarkTask) -> dict[str, str]:
    return {
        "benchmark_id": task.benchmark_id,
        "execution_profile": task.verification.execution_profile,
        "manifest_digest": task.manifest_digest,
        "row_digest": task.row_digest,
        "image_digest": _image_digest(task.environment.image),
        "baseline_digest": task.baseline_digest,
        "verification_digest": task.verification_digest,
    }


def _image_digest(reference: str) -> str:
    return reference.rsplit("@", 1)[1] if "@" in reference else reference


def _is_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    hexadecimal = value.removeprefix("sha256:")
    return len(hexadecimal) == 64 and all(character in "0123456789abcdef" for character in hexadecimal)


def _initialize_results_file(output_path: Path, records: list[dict[str, Any]]) -> None:
    """Atomically canonicalize resume state before append-only row persistence."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".results-", dir=output_path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output_file:
            for record in records:
                output_file.write(_encode_record(record))
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(temporary, output_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _encode_record(record: dict[str, Any]) -> str:
    return json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


def _summary_counters(records: list[dict[str, Any]]) -> dict[str, Any]:
    counters: dict[str, Any] = {
        "total": 0,
        "verified": 0,
        "passed": 0,
        "score_sum": 0.0,
        "infrastructure_errors": 0,
    }
    for record in records:
        _add_record(counters, record)
    return counters


def _add_record(counters: dict[str, Any], record: dict[str, Any]) -> None:
    counters["total"] += 1
    counters["verified"] += 1
    if record.get("passed") is True:
        counters["passed"] += 1
    score = record.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        counters["score_sum"] += float(score)
    if record.get("status") == "infrastructure_error":
        counters["infrastructure_errors"] += 1


def with_tester_overrides(
    config: TesterConfig,
    *,
    output_dir: str | Path | None = None,
    max_workers: int | None = None,
    max_cached_images: int | None = None,
) -> TesterConfig:
    updated = config
    if output_dir is not None:
        updated = replace(updated, run=replace(updated.run, output_dir=Path(output_dir)))
    if max_workers is not None:
        if isinstance(max_workers, bool) or max_workers <= 0:
            raise ConfigError("--workers must be a positive integer")
        updated = replace(updated, run=replace(updated.run, max_workers=max_workers))
    if max_cached_images is not None:
        if isinstance(max_cached_images, bool) or max_cached_images <= 0:
            raise ConfigError("--max-cached-images must be a positive integer")
        updated = replace(updated, docker=replace(updated.docker, max_cached_images=max_cached_images))
    return updated


class DockerImageBatchPruner:
    """Remove exact benchmark image references after each configured batch."""

    def __init__(self, max_cached_images: int | None) -> None:
        self.max_cached_images = max_cached_images
        self.pending: list[str] = []
        self.images_pruned = 0
        self.failures = 0

    def observe(self, image: str) -> None:
        if self.max_cached_images is None or image in self.pending:
            return
        self.pending.append(image)
        if len(self.pending) < self.max_cached_images:
            return
        targets = tuple(self.pending)
        self.pending.clear()
        emit_progress("image_prune_start", images=targets)
        try:
            completed = subprocess.run(
                ["docker", "image", "rm", "--force", "--", *targets],
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.failures += len(targets)
            emit_progress("image_prune_failed", images=targets, exit_code=None, stderr=str(exc))
            return
        if completed.returncode == 0:
            self.images_pruned += len(targets)
            emit_progress("image_prune_done", images=targets, removed=len(targets))
            return
        self.failures += len(targets)
        emit_progress(
            "image_prune_failed",
            images=targets,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
