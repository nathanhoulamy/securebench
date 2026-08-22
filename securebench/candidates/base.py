"""Base types for producing candidate answers and artifacts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from securebench.tasks import BenchmarkTask

if TYPE_CHECKING:
    from pathlib import Path

    from securebench.candidates.overlay_agent import OverlayAgentCaptureResult
    from securebench.candidates.store import CandidateStore


@dataclass(frozen=True)
class CandidateProduction:
    """Ephemeral output of an Agent harness, before trusted capture."""

    workspace: str | None = None
    stdout: str = ""
    stderr: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

class CandidateProducer(ABC):
    """Produce a candidate answer or artifact from agent-visible task data."""

    @abstractmethod
    def produce(self, task: BenchmarkTask, **context: Any) -> CandidateProduction:
        """Run the Agent and return state eligible for trusted capture."""

    def capture_filesystem_overlay(
        self,
        task: BenchmarkTask,
        *,
        store: CandidateStore,
        storage_root: Path,
        capacity_bytes: int,
        **context: Any,
    ) -> OverlayAgentCaptureResult:
        """Run and capture an overlay Candidate through the trusted orchestrator."""
        raise NotImplementedError
