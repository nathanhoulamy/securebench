"""Execution for tester YAML benchmark-pack harness runs."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.candidates import CandidateArtifact
from securebench.harnesses import build_harness_producer
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


def run_tester_config(config: TesterConfig, *, limit: int | None = None) -> TesterRunSummary:
    """Run tester YAML through candidate production and supported verification."""
    output_dir = config.run.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / DEFAULT_CANDIDATES_FILENAME
    workspace_root = output_dir / "workspaces"

    pack = load_benchmark_pack(config.benchmark.manifest, config.benchmark.tasks)
    producer = build_harness_producer(config.harness, workspace_root=workspace_root)

    total = 0
    verified = 0
    passed = 0
    score_sum = 0.0
    with output_path.open("w") as output_file:
        for task in compile_benchmark_pack(pack, limit=limit):
            candidate = producer.produce(task)
            verification = verify_candidate(task, candidate)
            record = candidate_record(config.run.id, task, candidate, verification)
            output_file.write(json.dumps(record, sort_keys=True) + "\n")
            total += 1
            if verification is not None:
                verified += 1
                if verification.passed:
                    passed += 1
                score_sum += verification.score

    return TesterRunSummary(
        run_id=config.run.id,
        output_dir=str(output_dir),
        output_path=str(output_path),
        total=total,
        verified=verified,
        passed=passed,
        score_sum=score_sum,
    )


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
