"""Registry of framework-owned isolation and orchestration profiles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from securebench.baselines import task_baseline_digest, task_verification_digest
from securebench.errors import ConfigError
from securebench.path_safety import (
    portable_path_is_relative_to,
    portable_paths_equal,
    portable_paths_overlap,
)
from securebench.schemas.benchmark import (
    ArtifactCheck,
    FileBundleCandidate,
    FilesystemOverlayCandidate,
    GitPatchCandidate,
    ProtocolCheck,
    RegularFileEntry,
)
from securebench.tasks import BenchmarkTask
from securebench.verification.models import VerificationInfrastructureError
from securebench.verification.oracle import load_oracle_manifest, oracle_resource_root
from securebench.verification.parsers import default_parser_registry
from securebench.verification.protocol import (
    load_adapter_manifest,
    require_supported_protocol_features,
)
from securebench.verification.trusted_helpers import default_trusted_helper_catalog


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

MAX_FILE_BUNDLE_BYTES = 256 * 1024 * 1024
MAX_FILE_BUNDLE_FILES = 10_000
MAX_GIT_PATCH_BYTES = 16 * 1024 * 1024
MAX_GIT_CHANGED_BYTES = 128 * 1024 * 1024
MAX_GIT_CHANGED_FILES = 2048
MAX_FILESYSTEM_OVERLAY_CHANGED_BYTES = 4 * 1024 * 1024 * 1024
MAX_FILESYSTEM_OVERLAY_CHANGED_PATHS = 50_000
MAX_PASSIVE_ARTIFACT_BYTES_PER_CHECK = 256 * 1024 * 1024
MAX_PASSIVE_ARTIFACT_FILES_PER_CHECK = 10_000
# This is deliberately changed only by the final reviewed native-Linux
# qualification commit. It has no environment-variable or tester-config bypass.
FILESYSTEM_OVERLAY_NATIVE_QUALIFICATION_COMPLETE = False


def execution_profile(profile_id: str) -> ExecutionProfile:
    try:
        return PROFILES[profile_id]
    except KeyError as exc:
        raise ConfigError(f"Unknown verification.execution_profile: {profile_id!r}") from exc


def validate_executable_task(task: BenchmarkTask) -> None:
    """Fail before Agent execution when the declared path is not implemented."""
    _validate_task_components(task, reject_unqualified_overlay=True)


def validate_task_components(task: BenchmarkTask) -> None:
    """Validate task components without asserting host capability qualification."""
    _validate_task_components(task, reject_unqualified_overlay=False)


def _validate_task_components(
    task: BenchmarkTask,
    *,
    reject_unqualified_overlay: bool,
) -> None:
    profile = execution_profile(task.verification.execution_profile)
    if not profile.implemented:
        raise ConfigError(f"Execution profile {profile.id!r} is registered but not implemented")
    candidate = task.verification.candidate
    _validate_candidate_bounds(candidate)
    if (
        isinstance(candidate, FilesystemOverlayCandidate)
        and reject_unqualified_overlay
        and not FILESYSTEM_OVERLAY_NATIVE_QUALIFICATION_COMPLETE
    ):
        raise ConfigError(
            "filesystem_overlay is schema-valid but not executable until the reviewed "
            "native-Linux qualification is complete"
        )
    if isinstance(candidate, FileBundleCandidate):
        workdir = PurePosixPath(task.environment.workdir)
        outside = [
            entry.id
            for entry in candidate.files
            if not PurePosixPath(entry.path).is_relative_to(workdir)
        ]
        if outside:
            raise ConfigError(
                "The current stopped-workspace capture backend requires file_bundle entries under "
                f"environment.workdir; outside entry ids: {', '.join(outside)}"
            )
        reserved_root = workdir / "securebench"
        for entry in candidate.files:
            if _paths_overlap(PurePosixPath(entry.path), reserved_root):
                raise ConfigError(
                    f"Candidate entry {entry.id!r} overlaps the framework materialization root "
                    f"{str(reserved_root)!r}"
                )
    _validate_public_assets(task)
    _validate_runtime_resources(task)
    _validate_oracle(task)
    _validate_parsers(task)
    _validate_artifact_bounds(task)
    _validate_protocol_checks(task)
    _validate_evaluation_mount_plan(task)
    if task_baseline_digest(task) != task.baseline_digest:
        raise ConfigError("Candidate-visible baseline resources changed after row compilation")
    if task_verification_digest(task) != task.verification_digest:
        raise ConfigError("Verification resources changed after row compilation")


def _validate_public_assets(task: BenchmarkTask) -> None:
    workdir = PurePosixPath(task.environment.workdir)
    candidate = task.verification.candidate
    for index, asset in enumerate(task.assets):
        if not asset.read_only:
            raise ConfigError(
                "The current stopped-workspace backend supports read-only public assets; "
                f"assets[{index}] is writable"
            )
        mount = PurePosixPath(asset.mount)
        if portable_paths_equal(mount, workdir):
            raise ConfigError(f"assets[{index}].mount may not replace environment.workdir")
        if portable_paths_overlap(mount, workdir / "securebench"):
            raise ConfigError(
                f"assets[{index}].mount overlaps the framework materialization root"
            )
        if isinstance(candidate, FileBundleCandidate):
            for entry in candidate.files:
                candidate_path = PurePosixPath(entry.path)
                if _paths_overlap(mount, candidate_path):
                    raise ConfigError(
                        f"assets[{index}].mount overlaps candidate entry {entry.id!r}; "
                        "mounted asset state is not part of stopped-workspace capture"
                    )


def _validate_candidate_bounds(
    candidate: FileBundleCandidate | GitPatchCandidate | FilesystemOverlayCandidate,
) -> None:
    if isinstance(candidate, FileBundleCandidate):
        if (
            candidate.max_total_files > MAX_FILE_BUNDLE_FILES
            or candidate.max_total_bytes > MAX_FILE_BUNDLE_BYTES
        ):
            raise ConfigError(
                "file_bundle candidate bounds exceed the capture backend capacity"
            )
        return
    if isinstance(candidate, FilesystemOverlayCandidate):
        if (
            candidate.max_changed_paths > MAX_FILESYSTEM_OVERLAY_CHANGED_PATHS
            or candidate.max_changed_bytes > MAX_FILESYSTEM_OVERLAY_CHANGED_BYTES
        ):
            raise ConfigError(
                "filesystem_overlay candidate bounds exceed the backend capacity"
            )
        return
    if (
        candidate.max_patch_bytes > MAX_GIT_PATCH_BYTES
        or candidate.max_changed_files > MAX_GIT_CHANGED_FILES
        or candidate.max_changed_bytes > MAX_GIT_CHANGED_BYTES
    ):
        raise ConfigError("git_patch candidate bounds exceed the capture backend capacity")


def _validate_artifact_bounds(task: BenchmarkTask) -> None:
    for check in task.verification.checks:
        if not isinstance(check, ArtifactCheck):
            continue
        total_bytes = sum(
            artifact.limits.max_bytes or artifact.limits.max_total_bytes or 0
            for artifact in check.artifacts
        )
        total_files = sum(
            artifact.limits.max_files or 1 for artifact in check.artifacts
        )
        if (
            total_bytes > MAX_PASSIVE_ARTIFACT_BYTES_PER_CHECK
            or total_files > MAX_PASSIVE_ARTIFACT_FILES_PER_CHECK
        ):
            raise ConfigError(
                f"Artifact check {check.id!r} bounds exceed the passive backend capacity"
            )


def _validate_parsers(task: BenchmarkTask) -> None:
    candidate = task.verification.candidate
    entries = (
        {entry.id: entry for entry in candidate.files}
        if isinstance(candidate, FileBundleCandidate)
        else {}
    )
    registry = default_parser_registry()
    for check in task.verification.checks:
        if isinstance(check, ProtocolCheck):
            for artifact in check.output_artifacts:
                try:
                    profile = registry.profile(artifact.parser)
                except KeyError as exc:
                    raise ConfigError(
                        f"Output artifact {artifact.name!r} uses unknown parser profile "
                        f"{artifact.parser!r}"
                    ) from exc
                expected = "bytes" if artifact.limits.max_bytes is not None else "tree"
                if profile.input_kind != expected:
                    raise ConfigError(
                        f"Output artifact {artifact.name!r} parser {artifact.parser!r} "
                        f"does not accept {expected!r} input"
                    )
            continue
        if not isinstance(check, ArtifactCheck):
            continue
        for artifact in check.artifacts:
            try:
                profile = registry.profile(artifact.parser)
            except KeyError as exc:
                raise ConfigError(
                    f"Artifact {artifact.id!r} uses unknown parser profile {artifact.parser!r}"
                ) from exc
            if isinstance(candidate, FileBundleCandidate):
                assert artifact.source.entry is not None
                entry = entries[artifact.source.entry]
                expected = "bytes" if isinstance(entry, RegularFileEntry) else "tree"
                source_kind = (
                    "regular_file" if isinstance(entry, RegularFileEntry) else "directory_tree"
                )
            else:
                assert artifact.source.path is not None
                path = PurePosixPath(artifact.source.path)
                if path.parts and path.parts[0].casefold() == ".git":
                    raise ConfigError(
                        f"Artifact {artifact.id!r} may not observe repository metadata"
                    )
                expected = "bytes" if artifact.limits.max_bytes is not None else "tree"
                source_kind = "repository file" if expected == "bytes" else "repository tree"
            if profile.input_kind != expected:
                raise ConfigError(
                    f"Artifact {artifact.id!r} parser {artifact.parser!r} does not accept "
                    f"candidate source kind {source_kind!r}"
                )


def _validate_runtime_resources(task: BenchmarkTask) -> None:
    workdir = PurePosixPath(task.environment.workdir)
    candidate = task.verification.candidate
    for identifier in task.verification.resources.runtime:
        resource = task.resources.resources.get(f"runtime.{identifier}")
        if resource is None or not isinstance(resource.value, dict):
            raise ConfigError(f"Runtime resource {identifier!r} is unavailable")
        mount_value = resource.value.get("mount")
        if not isinstance(mount_value, str):
            raise ConfigError(f"Runtime resource {identifier!r} has an invalid mount")
        mount = PurePosixPath(mount_value)
        if portable_paths_equal(mount, workdir):
            raise ConfigError(f"Runtime resource {identifier!r} may not replace environment.workdir")
        if portable_paths_overlap(mount, workdir / "securebench"):
            raise ConfigError(
                f"Runtime resource {identifier!r} overlaps the framework materialization root"
            )
        if isinstance(candidate, GitPatchCandidate) and portable_path_is_relative_to(
            mount, workdir
        ):
            raise ConfigError(
                f"Runtime resource {identifier!r} may not mount inside a git_patch repository"
            )
        if isinstance(candidate, FileBundleCandidate):
            for entry in candidate.files:
                if _paths_overlap(mount, PurePosixPath(entry.path)):
                    raise ConfigError(
                        f"Runtime resource {identifier!r} overlaps candidate entry {entry.id!r}; "
                        "mounted evaluation state is not part of stopped-workspace capture"
                    )


def _validate_protocol_checks(task: BenchmarkTask) -> None:
    trusted_helpers = default_trusted_helper_catalog()
    for check in task.verification.checks:
        if not isinstance(check, ProtocolCheck):
            continue
        try:
            manifest = load_adapter_manifest(task, check)
            require_supported_protocol_features(
                check,
                manifest,
                trusted_helpers,
                task=task,
            )
        except VerificationInfrastructureError as exc:
            raise ConfigError(
                f"Protocol check {check.id!r} is not executable: {exc.public_message}"
            ) from exc


def _validate_oracle(task: BenchmarkTask) -> None:
    try:
        load_oracle_manifest(oracle_resource_root(task))
    except VerificationInfrastructureError as exc:
        raise ConfigError(f"Oracle is not executable: {exc.public_message}") from exc


def _paths_overlap(left: PurePosixPath, right: PurePosixPath) -> bool:
    return portable_paths_overlap(left, right)


def _validate_evaluation_mount_plan(task: BenchmarkTask) -> None:
    from securebench.sandboxes import validate_docker_bind_mounts
    from securebench.workspaces.materialization import (
        VisibilityAwareMaterializer,
        docker_resource_mounts,
    )

    try:
        plan = VisibilityAwareMaterializer().build_plan(task, "evaluation_runtime")
        validate_docker_bind_mounts(
            docker_resource_mounts(plan),
            workspace_mount_target=task.environment.workdir,
        )
    except (OSError, ValueError) as exc:
        raise ConfigError(f"Evaluation resource mounts are not executable: {exc}") from exc
