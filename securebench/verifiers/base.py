"""Verifier interfaces for benchmark-pack task families."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from securebench.tasks import SecureBenchTask


@dataclass(frozen=True)
class VerificationResult:
    """Structured result returned by benchmark-family verifiers."""

    task_id: str
    status: str
    passed: bool
    score: float
    stdout: str = ""
    stderr: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class Verifier(ABC):
    """Verify one candidate artifact for a normalized benchmark-pack task."""

    @abstractmethod
    def verify(self, task: SecureBenchTask, candidate: str, **context: Any) -> VerificationResult:
        """Run family-specific verification and return a structured result."""
