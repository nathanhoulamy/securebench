"""Shared candidate artifact extraction for harness runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from securebench.candidates.base import CandidateProduction
from securebench.errors import ConfigError
from securebench.sandboxes import CommandResult, Sandbox
from securebench.tasks import BenchmarkTask


ExtractionMode = Literal["git_diff", "workspace"]


@dataclass(frozen=True)
class CandidateExtractionSpec:
    """How a harness exposes stopped state to trusted candidate capture."""

    mode: ExtractionMode
    candidate_type: str
    workdir: str | None = None


class CandidateProductionTimeout(Exception):
    """Raised when candidate production exceeded the benchmark time budget."""

    def __init__(self, result: CommandResult, *, phase: str = "producer") -> None:
        self.result = result
        self.phase = phase
        timeout = result.timeout_seconds
        if timeout is None:
            message = "candidate production timed out"
        else:
            message = f"candidate production timed out after {timeout:g} seconds"
        super().__init__(message)


class CandidateProductionError(Exception):
    """The Agent run ended without state eligible for candidate capture."""


def default_extraction_spec(
    task: BenchmarkTask,
) -> CandidateExtractionSpec:
    """Return the default extraction strategy for a task's candidate contract."""
    candidate_type = task.verification.candidate.type
    if candidate_type == "git_patch":
        return CandidateExtractionSpec(
            mode="git_diff",
            candidate_type=candidate_type,
            workdir=_task_workdir(task),
        )
    if candidate_type in {"file_bundle", "filesystem_overlay"}:
        return CandidateExtractionSpec(
            mode="workspace",
            candidate_type=candidate_type,
            workdir=_task_workdir(task),
        )
    raise ConfigError(f"Unsupported candidate type: {candidate_type!r}")


def extraction_instructions(spec: CandidateExtractionSpec) -> str:
    """Return prompt text that tells an agent how SecureBench will collect its answer."""
    if spec.mode == "git_diff":
        return (
            "Make the required repository changes in the workspace. "
            "SecureBench will collect the final git diff after you finish."
        )
    if spec.mode == "workspace":
        return "Make the required changes in the workspace. SecureBench will verify the final workspace state."
    raise ConfigError(f"Unsupported candidate extraction mode: {spec.mode!r}")


def extract_candidate(
    sandbox: Sandbox,
    run_result: CommandResult,
    spec: CandidateExtractionSpec,
    *,
    timeout: float | None = None,
) -> CandidateProduction:
    """Collect a candidate artifact according to a shared extraction spec."""
    if run_result.timed_out:
        raise CandidateProductionTimeout(run_result)
    if spec.mode == "git_diff":
        intent_result = sandbox.run(
            ["git", "add", "--intent-to-add", "--all", "--"],
            workdir=spec.workdir,
            timeout=timeout,
        )
        if intent_result.timed_out:
            raise CandidateProductionTimeout(intent_result, phase="candidate_extraction")
        if intent_result.exit_code != 0:
            raise ConfigError(
                "failed to prepare repository candidate extraction "
                f"(exit code {intent_result.exit_code}): {intent_result.stderr.strip()}"
            )
        diff_result = sandbox.run(
            ["git", "diff", "HEAD", "--binary", "--full-index", "--no-ext-diff", "--no-textconv", "--"],
            workdir=spec.workdir,
            timeout=timeout,
        )
        if diff_result.timed_out:
            raise CandidateProductionTimeout(diff_result, phase="candidate_extraction")
        if diff_result.exit_code != 0:
            raise ConfigError(
                "failed to extract repository candidate diff "
                f"(exit code {diff_result.exit_code}): {diff_result.stderr.strip()}"
            )
        return _candidate_artifact(
            spec,
            diff_result.stdout,
            stdout=run_result.stdout,
            stderr=run_result.stderr,
            metadata={
                **_metadata(spec),
                "candidate_diff_exit_code": diff_result.exit_code,
                "candidate_diff_stderr": diff_result.stderr,
            },
        )
    if spec.mode == "workspace":
        if run_result.exit_code != 0:
            raise CandidateProductionError(
                "harness command failed before producing a workspace candidate "
                f"(exit code {run_result.exit_code})"
            )
        workspace = str(getattr(sandbox, "root", ""))
        if not workspace:
            raise ConfigError("workspace candidate extraction requires sandbox.root")
        return CandidateProduction(
            workspace=workspace,
            stdout=run_result.stdout,
            stderr=run_result.stderr,
            metadata={
                **_metadata(spec),
                "candidate_workspace": workspace,
            },
        )
    raise ConfigError(f"Unsupported candidate extraction mode: {spec.mode!r}")


def _candidate_artifact(
    spec: CandidateExtractionSpec,
    candidate: str,
    *,
    stdout: str,
    stderr: str,
    metadata: dict[str, object],
) -> CandidateProduction:
    return CandidateProduction(
        patch=candidate if spec.candidate_type == "git_patch" else None,
        stdout=stdout,
        stderr=stderr,
        metadata=metadata,
    )


def _metadata(spec: CandidateExtractionSpec) -> dict[str, object]:
    metadata: dict[str, object] = {
        "candidate_type": spec.candidate_type,
        "candidate_extraction": spec.mode,
    }
    if spec.workdir is not None:
        metadata["candidate_workdir"] = spec.workdir
    return metadata


def _task_workdir(task: BenchmarkTask) -> str:
    return task.environment.workdir
