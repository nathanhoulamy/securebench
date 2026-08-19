"""Registry of framework-owned isolation and orchestration profiles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from securebench.errors import ConfigError
from securebench.schemas.benchmark import ArtifactCheck, FileBundleCandidate
from securebench.tasks import BenchmarkTask


@dataclass(frozen=True)
class ExecutionProfile:
    id: str
    description: str
    implemented: bool


PROFILES = {
    "strict-split/v1": ExecutionProfile(
        id="strict-split/v1",
        description="Fresh Agent sandbox per row followed by stopped-state capture and host Oracle verification",
        implemented=True,
    ),
    "batched-split/v1": ExecutionProfile(
        id="batched-split/v1",
        description="Weaker fresh-baseline batching fallback with per-row capture boundaries",
        implemented=False,
    ),
}


def execution_profile(profile_id: str) -> ExecutionProfile:
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        raise ConfigError(f"Unknown verification.execution_profile: {profile_id!r}") from exc


def validate_executable_task(task: BenchmarkTask) -> None:
    """Fail before Agent execution when the declared path is not implemented."""
    profile = execution_profile(task.verification.execution_profile)
    if not profile.implemented:
        raise ConfigError(f"Execution profile {profile.id!r} is registered but not implemented")
    if not isinstance(task.verification.candidate, FileBundleCandidate):
        raise ConfigError(
            "This implementation batch executes file_bundle candidates; "
            f"{task.verification.candidate.type!r} is schema-valid but not executable yet"
        )
    workdir = PurePosixPath(task.environment.workdir)
    outside = [
        entry.id
        for entry in task.verification.candidate.files
        if not PurePosixPath(entry.path).is_relative_to(workdir)
    ]
    if outside:
        raise ConfigError(
            "The current stopped-workspace capture backend requires file_bundle entries under "
            f"environment.workdir; outside entry ids: {', '.join(outside)}"
        )
    unsupported = [check.id for check in task.verification.checks if not isinstance(check, ArtifactCheck)]
    if unsupported:
        raise ConfigError(
            "This implementation batch executes artifact checks only; unsupported check ids: "
            + ", ".join(unsupported)
        )
