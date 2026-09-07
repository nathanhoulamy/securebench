"""Shared candidate artifact extraction for harness runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from securebench.candidates.base import CandidateProduction
from securebench.errors import ConfigError
from securebench.sandboxes import CommandResult, Sandbox
from securebench.tasks import BenchmarkTask


ExtractionMode = Literal["git_patch", "workspace"]


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
        mode = "git_patch"
    elif candidate_type in {"file_bundle", "filesystem_overlay"}:
        mode = "workspace"
    else:
        raise ConfigError(f"Unsupported candidate type: {candidate_type!r}")
    return CandidateExtractionSpec(
        mode=mode,
        candidate_type=candidate_type,
        workdir=task.environment.workdir,
    )


def extraction_instructions(spec: CandidateExtractionSpec) -> str:
    """Return prompt text that tells an agent how SecureBench will collect its answer."""
    if spec.mode == "git_patch":
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
) -> CandidateProduction:
    """Collect a candidate artifact according to a shared extraction spec."""
    if run_result.timed_out:
        raise CandidateProductionTimeout(run_result)
    if spec.mode not in {"git_patch", "workspace"}:
        raise ConfigError(f"Unsupported candidate extraction mode: {spec.mode!r}")
    if run_result.exit_code != 0:
        description = "git_patch workspace" if spec.mode == "git_patch" else "workspace candidate"
        raise CandidateProductionError(
            f"harness command failed before producing a {description} "
            f"(exit code {run_result.exit_code})"
        )
    workspace = str(getattr(sandbox, "root", ""))
    if not workspace:
        raise ConfigError("stopped-state candidate extraction requires sandbox.root")
    return CandidateProduction(
        workspace=workspace,
        stdout=run_result.stdout,
        stderr=run_result.stderr,
        metadata={
            **_metadata(spec),
            "candidate_workspace": workspace,
        },
    )


def _metadata(spec: CandidateExtractionSpec) -> dict[str, object]:
    metadata: dict[str, object] = {
        "candidate_type": spec.candidate_type,
        "candidate_extraction": spec.mode,
    }
    if spec.workdir is not None:
        metadata["candidate_workdir"] = spec.workdir
    return metadata
