"""Candidate production interfaces and implementations."""

from securebench.candidates.base import CandidateArtifact, CandidateProducer
from securebench.candidates.extraction import (
    CandidateExtractionSpec,
    CandidateProductionTimeout,
    default_extraction_spec,
    extract_candidate,
)
from securebench.candidates.capture import (
    HostWorkspaceFilesystem,
    capture_file_bundle,
    capture_git_patch,
)
from securebench.candidates.models import (
    CandidateCaptureError,
    CandidateReplayError,
    CandidateStoreError,
    StoredCandidate,
)
from securebench.candidates.replay import replay_file_bundle, replay_git_patch
from securebench.candidates.store import CandidateStore

__all__ = [
    "CandidateArtifact",
    "CandidateExtractionSpec",
    "CandidateProductionTimeout",
    "CandidateProducer",
    "CandidateCaptureError",
    "CandidateReplayError",
    "CandidateStore",
    "CandidateStoreError",
    "HostWorkspaceFilesystem",
    "StoredCandidate",
    "capture_file_bundle",
    "capture_git_patch",
    "default_extraction_spec",
    "extract_candidate",
    "replay_file_bundle",
    "replay_git_patch",
]
