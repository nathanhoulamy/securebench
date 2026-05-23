"""Execution for tester YAML benchmark-pack harness runs."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import CandidateArtifact
from securebench.harnesses.shared import workspace_dir_name
from securebench.harnesses import build_harness_producer
from securebench.progress import ProgressReporter, emit_progress, progress_context
from securebench.resources import REDACTED
from securebench.tester_config import TesterConfig
from securebench.verifiers import VerificationResult, verifier_for_task_type


DEFAULT_CANDIDATES_FILENAME = "candidates.jsonl"
UNSUPPORTED_VERIFICATION_STATUS = "pending"


@dataclass(frozen=True)
class TesterRunSummary:
    """Aggregate information for a tester YAML candidate-production run."""

    run_id: str
    output_dir: str
    output_path: str
    total: int
    verified: int = 0
    passed: int = 0
    score_sum: float = 0.0

    @property
    def verification_status(self) -> str:
        if self.total == 0:
            return "complete"
        if self.verified == 0:
            return UNSUPPORTED_VERIFICATION_STATUS
        if self.verified == self.total:
            return "complete"
        return "partial"


def run_tester_config(
    config: TesterConfig,
    *,
    limit: int | None = None,
    progress: ProgressReporter | None = None,
    resume: bool = False,
) -> TesterRunSummary:
    """Run tester YAML through candidate production and supported verification."""
    output_dir = config.run.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / DEFAULT_CANDIDATES_FILENAME
    workspace_root = output_dir / "workspaces"

    pack = load_benchmark_pack(config.benchmark.manifest, config.benchmark.tasks)
    producer = build_harness_producer(config.harness, workspace_root=workspace_root)

    tasks = list(compile_benchmark_pack(pack, limit=limit))
    existing_records = _resume_records(output_path) if resume else []
    completed_task_ids = {
        record["task_id"]
        for record in existing_records
        if isinstance(record.get("task_id"), str)
    }
    remaining_tasks = [task for task in tasks if task.id not in completed_task_ids]
    total = len(existing_records)
    verified = 0
    passed = 0
    score_sum = 0.0
    for record in existing_records:
        if _record_is_verified(record):
            verified += 1
            if record.get("passed") is True:
                passed += 1
            score_sum += _record_score(record)
    with progress_context(progress):
        emit_progress("run_start", run_id=config.run.id, output_dir=output_dir)
        if existing_records:
            emit_progress(
                "resume",
                completed=len(existing_records),
                remaining=len(remaining_tasks),
                output_path=output_path,
            )
        with output_path.open("w") as output_file:
            if resume and existing_records:
                for record in existing_records:
                    output_file.write(json.dumps(record, sort_keys=True) + "\n")
                output_file.flush()
            for task in remaining_tasks:
                emit_progress(
                    "task_start",
                    index=total + 1,
                    total=len(tasks),
                    task_id=task.id,
                    family=task.task_type,
                )
                emit_progress("producer_start", task_id=task.id)
                _reset_task_workspace(workspace_root, task)
                candidate = producer.produce(task)
                emit_progress(
                    "producer_done",
                    task_id=task.id,
                    candidate_kind=_candidate_kind(candidate),
                )
                emit_progress("verifier_start", task_id=task.id)
                verification = verify_candidate(task, candidate)
                emit_progress(
                    "verifier_done",
                    task_id=task.id,
                    status=None if verification is None else verification.status,
                    score=None if verification is None else verification.score,
                    phase=_verification_phase(verification),
                )
                record = candidate_record(config.run.id, task, candidate, verification)
                output_file.write(json.dumps(record, sort_keys=True) + "\n")
                output_file.flush()
                total += 1
                if verification is not None:
                    verified += 1
                    if verification.passed:
                        passed += 1
                    score_sum += verification.score
                emit_progress(
                    "task_done",
                    task_id=task.id,
                    status=record["verification_status"],
                    passed=record.get("passed"),
                    score=record.get("score"),
                )

    return TesterRunSummary(
        run_id=config.run.id,
        output_dir=str(output_dir),
        output_path=str(output_path),
        total=total,
        verified=verified,
        passed=passed,
        score_sum=score_sum,
    )


def _reset_task_workspace(workspace_root: Path, task: Any) -> None:
    """Remove stale per-task workspace state before a fresh producer run."""
    task_workspace = (workspace_root / workspace_dir_name(task)).resolve()
    root = workspace_root.resolve()
    if not task_workspace.is_relative_to(root):
        raise ValueError(f"task workspace escapes workspace root: {task_workspace}")
    if task_workspace.exists():
        shutil.rmtree(task_workspace)


def _resume_records(output_path: Path) -> list[dict[str, Any]]:
    if not output_path.exists():
        return []
    records = []
    for line in output_path.read_text(errors="ignore").splitlines():
        line = line.strip("\x00").strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and isinstance(record.get("task_id"), str):
            records.append(record)
    return records


def _record_is_verified(record: dict[str, Any]) -> bool:
    return record.get("verification_status") != UNSUPPORTED_VERIFICATION_STATUS


def _record_score(record: dict[str, Any]) -> float:
    score = record.get("score", 0.0)
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return float(score)
    return 0.0


def _candidate_kind(candidate: CandidateArtifact) -> str:
    if candidate.patch is not None:
        return "patch"
    if candidate.workspace is not None:
        return "workspace"
    if candidate.text is not None:
        return "text"
    return "none"


def _verification_phase(verification: VerificationResult | None) -> object:
    if verification is None:
        return None
    return verification.metadata.get("phase")


def with_tester_overrides(
    config: TesterConfig,
    *,
    output_dir: str | Path | None = None,
) -> TesterConfig:
    """Return a tester config with CLI overrides applied."""
    if output_dir is None:
        return config
    return replace(config, run=replace(config.run, output_dir=Path(output_dir)))


def verify_candidate(task: Any, candidate: CandidateArtifact) -> VerificationResult | None:
    """Verify a candidate when SecureBench has a verifier for the task family."""
    verifier = verifier_for_task_type(task.task_type)
    if verifier is None:
        return None
    return verifier.verify(task, candidate.for_task(task))


def candidate_record(
    run_id: str,
    task: Any,
    candidate: CandidateArtifact,
    verification: VerificationResult | None = None,
) -> dict[str, object]:
    """Serialize one candidate-production result plus optional verifier output."""
    record: dict[str, object] = {
        "run_id": run_id,
        "task_id": task.id,
        "benchmark_id": task.benchmark_id,
        "task_type": task.task_type,
        "verification_status": UNSUPPORTED_VERIFICATION_STATUS,
        "candidate_text": candidate.text,
        "candidate_patch": candidate.patch,
        "candidate_workspace": candidate.workspace,
        "producer_stdout": candidate.stdout,
        "producer_stderr": candidate.stderr,
        "producer_metadata": candidate.metadata,
        "resource_summary": task.resource_summary(),
        "hidden_values": REDACTED,
    }
    if verification is None:
        return record

    record.update(
        {
            "verification_status": verification.status,
            "passed": verification.passed,
            "score": verification.score,
            "verifier_stdout": verification.stdout,
            "verifier_stderr": verification.stderr,
            "verifier_metadata": _redact_verifier_metadata(verification.metadata, task),
        }
    )
    return record


def _redact_verifier_metadata(metadata: dict[str, Any], task: Any) -> dict[str, Any]:
    hidden_values = _hidden_values(task)
    redacted = _redact_exact_hidden_values(metadata, hidden_values)
    if "expected_answer" in redacted:
        redacted["expected_answer"] = REDACTED
    return redacted


def _hidden_values(task: Any) -> tuple[Any, ...]:
    resources = getattr(task, "resources", None)
    if resources is None:
        return ()
    return tuple(
        resource.value
        for resource in resources.by_visibility("hidden")
        if resource.value not in (None, "", (), [], {})
    )


def _redact_exact_hidden_values(value: Any, hidden_values: tuple[Any, ...]) -> Any:
    if any(value == hidden for hidden in hidden_values):
        return REDACTED
    if isinstance(value, dict):
        return {key: _redact_exact_hidden_values(item, hidden_values) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_exact_hidden_values(item, hidden_values) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_exact_hidden_values(item, hidden_values) for item in value)
    return value
