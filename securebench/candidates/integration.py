"""Trusted boundary between ephemeral Agent output and durable candidates."""

from __future__ import annotations

from pathlib import Path

from securebench.baselines import task_baseline_digest
from securebench.candidates.base import CandidateProduction
from securebench.candidates.capture import HostWorkspaceFilesystem, capture_file_bundle, capture_git_patch
from securebench.candidates.models import CandidateCaptureError, StoredCandidate
from securebench.candidates.store import CandidateStore
from securebench.schemas.benchmark import FileBundleCandidate, GitPatchCandidate
from securebench.tasks import BenchmarkTask


def capture_production(
    task: BenchmarkTask,
    production: CandidateProduction,
    store: CandidateStore,
) -> StoredCandidate:
    """Capture declared durable state after the Agent sandbox has stopped."""
    spec = task.verification.candidate
    baseline_digest = task_baseline_digest(task)
    if isinstance(spec, FileBundleCandidate):
        root = _workspace_root(production)
        filesystem = HostWorkspaceFilesystem(root, guest_root=task.environment.workdir)
        return capture_file_bundle(filesystem, spec, store, baseline_digest=baseline_digest)
    if isinstance(spec, GitPatchCandidate):
        if production.patch is None:
            raise CandidateCaptureError("Agent production did not expose a git patch")
        return capture_git_patch(
            production.patch,
            _workspace_root(production),
            spec,
            store,
            baseline_digest=baseline_digest,
        )
    raise CandidateCaptureError(
        f"candidate capture is not implemented for {spec.type!r}"
    )


def _workspace_root(production: CandidateProduction) -> Path:
    value = production.workspace
    if value is None:
        metadata_value = production.metadata.get("workspace_root")
        value = metadata_value if isinstance(metadata_value, str) else None
    if value is None:
        raise CandidateCaptureError("Agent production did not expose its stopped workspace")
    root = Path(value).resolve()
    if not root.is_dir():
        raise CandidateCaptureError(f"Agent workspace does not exist: {root}")
    return root
