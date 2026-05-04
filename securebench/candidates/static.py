"""Static candidate producer for tests and fixtures."""

from __future__ import annotations

from typing import Any

from securebench.candidates.base import CandidateArtifact, CandidateProducer
from securebench.tasks import SecureBenchTask


class StaticCandidateProducer(CandidateProducer):
    """Return the same candidate artifact for every task."""

    def __init__(self, artifact: CandidateArtifact | str) -> None:
        if isinstance(artifact, CandidateArtifact):
            self.artifact = artifact
        else:
            self.artifact = CandidateArtifact(text=artifact)

    def produce(self, task: SecureBenchTask, **context: Any) -> CandidateArtifact:
        return self.artifact
