"""Verifier interfaces for benchmark-pack task families."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from securebench.sandboxes.base import CommandResult
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


def timeout_metadata(result: CommandResult) -> dict[str, object]:
    """Return common verifier metadata for sandbox command timeouts."""
    if not result.timed_out:
        return {}
    return {
        "failure_reason": "verifier_timeout",
        "timed_out": True,
        "timeout_seconds": result.timeout_seconds,
    }
