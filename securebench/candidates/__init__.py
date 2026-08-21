"""Candidate production interfaces and implementations."""

from securebench.candidates.base import CandidateProducer, CandidateProduction
from securebench.candidates.extraction import (
    CandidateExtractionSpec,
    CandidateProductionError,
    CandidateProductionTimeout,
    default_extraction_spec,
    extract_candidate,
)
from securebench.candidates.capture import (
    HostWorkspaceFilesystem,
    capture_file_bundle,
    capture_git_patch,
    capture_git_patch_workspace,
)
from securebench.candidates.integration import capture_production
from securebench.candidates.models import (
    CandidateCaptureError,
    CandidateReplayError,
    CandidateStoreError,
    StoredCandidate,
)
from securebench.candidates.overlay import (
    OverlayScanLimits,
    capture_filesystem_overlay,
    capture_filesystem_overlay_from_baseline,
    scan_overlay_root,
    scan_overlay_roots,
)
from securebench.candidates.overlay_agent import (
    OverlayAgentCaptureResult,
    OverlayAgentInfrastructureError,
    materialize_overlay_image_roots,
    run_filesystem_overlay_agent_capture,
)
from securebench.candidates.replay import replay_candidate, replay_file_bundle, replay_git_patch
from securebench.candidates.store import CandidateStore

__all__ = [
    "CandidateProduction",
    "CandidateExtractionSpec",
    "CandidateProductionError",
    "CandidateProductionTimeout",
    "CandidateProducer",
    "CandidateCaptureError",
    "CandidateReplayError",
    "CandidateStore",
    "CandidateStoreError",
    "HostWorkspaceFilesystem",
    "OverlayScanLimits",
    "OverlayAgentCaptureResult",
    "OverlayAgentInfrastructureError",
    "StoredCandidate",
    "capture_file_bundle",
    "capture_filesystem_overlay",
    "capture_filesystem_overlay_from_baseline",
    "capture_git_patch",
    "capture_git_patch_workspace",
    "capture_production",
    "default_extraction_spec",
    "extract_candidate",
    "materialize_overlay_image_roots",
    "replay_file_bundle",
    "replay_git_patch",
    "replay_candidate",
    "scan_overlay_root",
    "scan_overlay_roots",
    "run_filesystem_overlay_agent_capture",
]
