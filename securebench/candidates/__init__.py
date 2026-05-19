"""Candidate production interfaces and implementations."""

from securebench.candidates.base import CandidateArtifact, CandidateProducer
from securebench.candidates.extraction import (
    CandidateExtractionSpec,
    default_extraction_spec,
    extract_candidate,
)

__all__ = [
    "CandidateArtifact",
    "CandidateExtractionSpec",
    "CandidateProducer",
    "default_extraction_spec",
    "extract_candidate",
]
