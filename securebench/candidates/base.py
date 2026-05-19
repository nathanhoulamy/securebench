"""Base types for producing candidate answers and artifacts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from securebench.tasks import SecureBenchTask


@dataclass(frozen=True)
class CandidateArtifact:
    """Output produced by a model, script, or workspace agent."""

    text: str | None = None
    patch: str | None = None
    stdout: str = ""
    stderr: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def for_task(self, task: SecureBenchTask) -> str:
        """Return the artifact value expected by the task's verifier."""
        if task.task_type == "repo_patch":
            return self.patch or ""
        return self.text or ""


class CandidateProducer(ABC):
    """Produce a candidate answer or artifact from agent-visible task data."""

    @abstractmethod
    def produce(self, task: SecureBenchTask, **context: Any) -> CandidateArtifact:
        """Produce a candidate artifact for a normalized task."""
