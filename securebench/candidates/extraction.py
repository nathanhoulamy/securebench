"""Shared candidate artifact extraction for harness runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from securebench.candidates.base import CandidateArtifact
from securebench.errors import ConfigError
from securebench.families import family_contract_for
from securebench.sandboxes import CommandResult, Sandbox
from securebench.tasks import SecureBenchTask


DEFAULT_CODE_CANDIDATE_FILE = "candidate.py"
DEFAULT_TEXT_CANDIDATE_FILE = "candidate.txt"

ExtractionMode = Literal["stdout", "file", "git_diff", "workspace", "unsupported"]


@dataclass(frozen=True)
class CandidateExtractionSpec:
    """How SecureBench should collect a family-shaped candidate after a harness run."""

    mode: ExtractionMode
    candidate_kind: str
    path: str | None = None
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
    if contract.candidate_kind == "workspace":
        return CandidateExtractionSpec(
            mode="workspace",
            candidate_kind=contract.candidate_kind,
            workdir=_task_workdir(task),
        )
    if contract.candidate_kind == "text":
        if allow_stdout:
            return CandidateExtractionSpec(mode="stdout", candidate_kind=contract.candidate_kind)
        return CandidateExtractionSpec(
            mode="file",
            candidate_kind=contract.candidate_kind,
            path=DEFAULT_TEXT_CANDIDATE_FILE,
        )
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
    if spec.mode == "workspace":
        return "Make the required changes in the workspace. SecureBench will verify the final workspace state."
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
    if run_result.timed_out:
        raise CandidateProductionTimeout(run_result)
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
            raise ConfigError(
                "harness command failed before producing a workspace candidate "
                f"(exit code {run_result.exit_code})"
            )
        workspace = str(getattr(sandbox, "root", ""))
        if not workspace:
            raise ConfigError("workspace candidate extraction requires sandbox.root")
        return CandidateArtifact(
            workspace=workspace,
            stdout=run_result.stdout,
            stderr=run_result.stderr,
            metadata={
                **_metadata(spec),
                "candidate_workspace": workspace,
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
