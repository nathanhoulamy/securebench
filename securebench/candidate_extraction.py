"""Shared candidate artifact extraction for harness runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from securebench.candidates import CandidateArtifact
from securebench.errors import ConfigError
from securebench.families import family_contract_for
from securebench.sandboxes import CommandResult, Sandbox
from securebench.tasks import SecureBenchTask


DEFAULT_CODE_CANDIDATE_FILE = "candidate.py"

ExtractionMode = Literal["stdout", "file", "git_diff", "unsupported"]


@dataclass(frozen=True)
class CandidateExtractionSpec:
    """How SecureBench should collect a family-shaped candidate after a harness run."""

    mode: ExtractionMode
    candidate_kind: str
    path: str | None = None
    workdir: str | None = None


def default_extraction_spec(
    task: SecureBenchTask,
    *,
    allow_stdout: bool = True,
) -> CandidateExtractionSpec:
    """Return the default extraction strategy for a task's candidate contract."""
    contract = family_contract_for(task.task_type)
    if contract.candidate_kind == "code":
        return CandidateExtractionSpec(
            mode="file",
            candidate_kind=contract.candidate_kind,
            path=DEFAULT_CODE_CANDIDATE_FILE,
        )
    if contract.candidate_kind == "patch":
        return CandidateExtractionSpec(
            mode="git_diff",
            candidate_kind=contract.candidate_kind,
            workdir=_task_workdir(task),
        )
    if contract.candidate_kind == "text" and allow_stdout:
        return CandidateExtractionSpec(mode="stdout", candidate_kind=contract.candidate_kind)
    return CandidateExtractionSpec(mode="unsupported", candidate_kind=contract.candidate_kind)


def stdout_extraction_spec(task: SecureBenchTask) -> CandidateExtractionSpec:
    """Return a stdout extraction spec shaped for the task's candidate contract."""
    contract = family_contract_for(task.task_type)
    return CandidateExtractionSpec(mode="stdout", candidate_kind=contract.candidate_kind)


def file_extraction_spec(task: SecureBenchTask, path: str) -> CandidateExtractionSpec:
    """Return a file extraction spec shaped for the task's candidate contract."""
    contract = family_contract_for(task.task_type)
    return CandidateExtractionSpec(mode="file", candidate_kind=contract.candidate_kind, path=path)


def extraction_instructions(spec: CandidateExtractionSpec) -> str:
    """Return prompt text that tells an agent how SecureBench will collect its answer."""
    if spec.mode == "file":
        return (
            f"Write the final candidate to {spec.path}. "
            "The file should contain only the content needed by the evaluator."
        )
    if spec.mode == "git_diff":
        return (
            "Make the required repository changes in the workspace. "
            "SecureBench will collect the final git diff after you finish."
        )
    if spec.mode == "stdout":
        return "Print the final candidate to stdout."
    return "Leave your final work in the workspace."


def extract_candidate(
    task: SecureBenchTask,
    sandbox: Sandbox,
    run_result: CommandResult,
    spec: CandidateExtractionSpec,
    *,
    timeout: float | None = None,
) -> CandidateArtifact:
    """Collect a candidate artifact according to a shared extraction spec."""
    if spec.mode == "stdout":
        candidate = run_result.stdout
        return _candidate_artifact(
            spec,
            candidate,
            stdout=run_result.stdout,
            stderr=run_result.stderr,
            metadata=_metadata(spec),
        )
    if spec.mode == "file":
        if spec.path is None:
            raise ConfigError("candidate extraction file mode requires a path")
        try:
            candidate = sandbox.read_file(spec.path)
        except FileNotFoundError as exc:
            raise ConfigError(f"harness did not produce expected candidate file: {spec.path}") from exc
        return _candidate_artifact(
            spec,
            candidate,
            stdout=run_result.stdout,
            stderr=run_result.stderr,
            metadata=_metadata(spec),
        )
    if spec.mode == "git_diff":
        diff_result = sandbox.run(["git", "diff", "--binary"], workdir=spec.workdir, timeout=timeout)
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
    return CandidateArtifact(
        stdout=run_result.stdout,
        stderr=run_result.stderr,
        metadata=_metadata(spec),
    )


def _candidate_artifact(
    spec: CandidateExtractionSpec,
    candidate: str,
    *,
    stdout: str,
    stderr: str,
    metadata: dict[str, object],
) -> CandidateArtifact:
    return CandidateArtifact(
        text=candidate if spec.candidate_kind in {"text", "code"} else None,
        patch=candidate if spec.candidate_kind == "patch" else None,
        stdout=stdout,
        stderr=stderr,
        metadata=metadata,
    )


def _metadata(spec: CandidateExtractionSpec) -> dict[str, object]:
    metadata: dict[str, object] = {
        "candidate_kind": spec.candidate_kind,
        "candidate_extraction": spec.mode,
    }
    if spec.path is not None:
        metadata["candidate_path"] = spec.path
    if spec.workdir is not None:
        metadata["candidate_workdir"] = spec.workdir
    return metadata


def _task_workdir(task: SecureBenchTask) -> str | None:
    metadata = task.metadata if isinstance(task.metadata, dict) else {}
    environment = metadata.get("environment")
    if not isinstance(environment, dict):
        return None
    workdir = environment.get("workdir")
    if not isinstance(workdir, str) or not workdir.strip():
        return None
    return workdir.strip()
