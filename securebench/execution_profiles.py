"""Registry of framework-owned isolation and orchestration profiles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from securebench.baselines import task_baseline_digest, task_verification_digest
from securebench.errors import ConfigError
from securebench.schemas.benchmark import (
    ArtifactCheck,
    FileBundleCandidate,
    RegularFileEntry,
)
from securebench.tasks import BenchmarkTask
from securebench.verification.parsers import default_parser_registry


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
    _validate_public_assets(task)
    _validate_parsers(task)
    if task_baseline_digest(task) != task.baseline_digest:
        raise ConfigError("Candidate-visible baseline resources changed after row compilation")
    if task_verification_digest(task) != task.verification_digest:
        raise ConfigError("Verification resources changed after row compilation")


def _validate_public_assets(task: BenchmarkTask) -> None:
    workdir = PurePosixPath(task.environment.workdir)
    candidate = task.verification.candidate
    assert isinstance(candidate, FileBundleCandidate)
    for index, asset in enumerate(task.assets):
        if not asset.read_only:
            raise ConfigError(
                "The current stopped-workspace backend supports read-only public assets; "
                f"assets[{index}] is writable"
            )
        mount = PurePosixPath(asset.mount)
        if mount == workdir:
            raise ConfigError(f"assets[{index}].mount may not replace environment.workdir")
        for entry in candidate.files:
            candidate_path = PurePosixPath(entry.path)
            if (
                mount == candidate_path
                or mount.is_relative_to(candidate_path)
                or candidate_path.is_relative_to(mount)
            ):
                raise ConfigError(
                    f"assets[{index}].mount overlaps candidate entry {entry.id!r}; "
                    "mounted asset state is not part of stopped-workspace capture"
                )


def _validate_parsers(task: BenchmarkTask) -> None:
    candidate = task.verification.candidate
    assert isinstance(candidate, FileBundleCandidate)
    entries = {entry.id: entry for entry in candidate.files}
    registry = default_parser_registry()
    for check in task.verification.checks:
        assert isinstance(check, ArtifactCheck)
        for artifact in check.artifacts:
            try:
                profile = registry.profile(artifact.parser)
            except KeyError as exc:
                raise ConfigError(
                    f"Artifact {artifact.id!r} uses unknown parser profile {artifact.parser!r}"
                ) from exc
            assert artifact.source.entry is not None
            entry = entries[artifact.source.entry]
            expected = "bytes" if isinstance(entry, RegularFileEntry) else "tree"
            if profile.input_kind != expected:
                kind = "regular_file" if isinstance(entry, RegularFileEntry) else "directory_tree"
                raise ConfigError(
                    f"Artifact {artifact.id!r} parser {artifact.parser!r} does not accept "
                    f"candidate entry kind {kind!r}"
                )
