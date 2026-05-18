"""Small evaluator orchestration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from securebench.adapters import get_adapter
from securebench.candidates import CandidateArtifact, CandidateProducer
from securebench.runners import CodeCompletionRunner, GitHubPatchRunner, MultipleChoiceRunner, Runner, RunnerResult
from securebench.tasks import SecureBenchTask


@dataclass(frozen=True)
class EvaluationResult:
    """Combined result from candidate production and task evaluation."""

    task: SecureBenchTask
    candidate: CandidateArtifact
    runner_result: RunnerResult

    @property
    def passed(self) -> bool:
        return self.runner_result.passed

    @property
    def score(self) -> float:
        return self.runner_result.score


def evaluate_task(
    task: SecureBenchTask,
    producer: CandidateProducer,
    *,
    runner: Runner | None = None,
    producer_context: dict[str, Any] | None = None,
    runner_context: dict[str, Any] | None = None,
) -> EvaluationResult:
    """Produce a candidate for a normalized task and evaluate it."""
    selected_runner = runner or get_runner(task.task_type)
    candidate = producer.produce(task, **(producer_context or {}))
    runner_result = selected_runner.run(task, candidate.for_task(task), **(runner_context or {}))
    return EvaluationResult(task=task, candidate=candidate, runner_result=runner_result)


def evaluate_row(
    adapter_id: str,
    row: dict[str, Any],
    producer: CandidateProducer,
    *,
    adapter_context: dict[str, Any] | None = None,
    runner: Runner | None = None,
    producer_context: dict[str, Any] | None = None,
    runner_context: dict[str, Any] | None = None,
) -> EvaluationResult:
    """Adapt one raw benchmark row, produce a candidate, and evaluate it."""
    task = get_adapter(adapter_id).to_task(row, **(adapter_context or {}))
    return evaluate_task(
        task,
        producer,
        runner=runner,
        producer_context=producer_context,
        runner_context=runner_context,
    )


def get_runner(task_type: str) -> Runner:
    """Return the built-in runner for a normalized task type."""
    if task_type == "multiple_choice":
        return MultipleChoiceRunner()
    if task_type == "code_completion":
        return CodeCompletionRunner()
    if task_type == "github_patch":
        return GitHubPatchRunner()
    raise KeyError(f"Unknown task type {task_type!r}")
