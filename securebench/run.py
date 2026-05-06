"""Batch execution for SecureBench run configs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from securebench.config import RunConfig
from securebench.datasets import DatasetRow
from securebench.evaluator import EvaluationResult, evaluate_row
from securebench.resources import REDACTED


@dataclass(frozen=True)
class RunSummary:
    """Aggregate information for one benchmark run."""

    run_id: str
    output_path: str
    total: int
    passed: int
    score_sum: float

    @property
    def accuracy(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    @property
    def average_score(self) -> float:
        if self.total == 0:
            return 0.0
        return self.score_sum / self.total


def run_config(config: RunConfig, *, rows: Iterable[DatasetRow] | None = None) -> RunSummary:
    """Run a benchmark config over dataset rows and write JSONL results."""
    dataset_rows = rows if rows is not None else config.dataset_ref().iter_rows(limit=config.run.limit)
    adapter = config.build_adapter()
    producer = config.build_producer()
    runner = config.build_runner()

    output_path = config.run.output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    passed = 0
    score_sum = 0.0

    with output_path.open("w") as output_file:
        for item in dataset_rows:
            if rows is not None and config.run.limit is not None and total >= config.run.limit:
                break

            result = evaluate_row(
                adapter.benchmark_id,
                item.row,
                producer,
                adapter_context=item.context,
                runner=runner,
            )
            record = result_to_record(config.run.id, result)
            output_file.write(json.dumps(record, sort_keys=True) + "\n")

            total += 1
            if result.passed:
                passed += 1
            score_sum += result.score

    return RunSummary(
        run_id=config.run.id,
        output_path=str(output_path),
        total=total,
        passed=passed,
        score_sum=score_sum,
    )


def result_to_record(run_id: str, result: EvaluationResult) -> dict[str, object]:
    """Serialize one evaluation result to a JSONL-safe dictionary."""
    return {
        "run_id": run_id,
        "task_id": result.task.id,
        "benchmark_id": result.task.benchmark_id,
        "task_type": result.task.task_type,
        "passed": result.passed,
        "score": result.score,
        "candidate_text": result.candidate.text,
        "candidate_patch": result.candidate.patch,
        "producer_stdout": result.candidate.stdout,
        "producer_stderr": result.candidate.stderr,
        "producer_metadata": result.candidate.metadata,
        "runner_stdout": result.runner_result.stdout,
        "runner_stderr": result.runner_result.stderr,
        "runner_metadata": _redact_runner_metadata(result.runner_result.metadata, result.task),
        "resource_summary": result.task.resource_summary(),
    }


def _redact_runner_metadata(metadata: dict[str, Any], task: object) -> dict[str, Any]:
    hidden_values = _hidden_values(task)
    redacted = _redact_exact_hidden_values(metadata, hidden_values)
    if "expected_answer" in redacted:
        redacted["expected_answer"] = REDACTED
    return redacted


def _hidden_values(task: object) -> tuple[Any, ...]:
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
