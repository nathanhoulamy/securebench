"""Trusted boundary between ephemeral Agent output and durable candidates."""

from __future__ import annotations

import tempfile
from pathlib import Path

from securebench.candidates.base import CandidateProduction
from securebench.candidates.capture import (
    HostWorkspaceFilesystem,
    capture_file_bundle,
    capture_git_patch_workspace,
)
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
    if isinstance(spec, FileBundleCandidate):
        root = _workspace_root(production)
        filesystem = HostWorkspaceFilesystem(root, guest_root=task.environment.workdir)
        return capture_file_bundle(filesystem, spec, store, baseline_digest=task.baseline_digest)
    if isinstance(spec, GitPatchCandidate):
        root = _workspace_root(production)
        task_file = production.metadata.get("task_file")
        protected_paths = (task_file,) if isinstance(task_file, str) else ()
        base_commit = task.input.get("base_commit")
        if not isinstance(base_commit, str):
            raise CandidateCaptureError("repo_patch task has no canonical base_commit")
        # Import lazily: harness modules import candidate integration.
        from securebench.harnesses.shared import materialize_image_workdir

        with tempfile.TemporaryDirectory(prefix="securebench-patch-baseline-") as temporary_name:
            baseline = Path(temporary_name) / "repository"
            materialize_image_workdir(task, baseline)
            return capture_git_patch_workspace(
                root,
                baseline,
                spec,
                store,
                baseline_digest=task.baseline_digest,
                base_commit=base_commit,
                protected_paths=protected_paths,
            )
    raise CandidateCaptureError(f"candidate capture is not implemented for {spec.type!r}")


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
