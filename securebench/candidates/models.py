"""Durable split-verification candidate models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


CandidateType = Literal["git_patch", "file_bundle", "filesystem_overlay"]
CANDIDATE_MANIFEST_VERSION = "1"


@dataclass(frozen=True)
class StoredCandidate:
    """Reference to one immutable content-addressed candidate manifest."""

    type: CandidateType
    digest: str
    manifest_path: Path
    baseline_digest: str


@dataclass(frozen=True)
class CandidateManifest:
    """Validated candidate manifest loaded from the artifact store."""

    schema_version: str
    type: CandidateType
    baseline_digest: str
    payload: dict[str, Any]


class CandidateCaptureError(ValueError):
    """Raised when an Agent workspace cannot be captured safely."""


class CandidateStoreError(ValueError):
    """Raised when a stored candidate or blob fails integrity checks."""


class CandidateReplayError(ValueError):
    """Raised when a candidate cannot be replayed on its declared baseline."""
