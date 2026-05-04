"""Base interfaces for executing normalized tasks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from securebench.tasks import SecureBenchTask


@dataclass(frozen=True)
class RunnerResult:
    """Structured result returned by task runners."""

    task_id: str
    passed: bool
    score: float
    stdout: str = ""
    stderr: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class Runner(ABC):
    """Execute one normalized task against a candidate response or artifact."""

    @abstractmethod
    def run(self, task: SecureBenchTask, candidate: Any, **context: Any) -> RunnerResult:
        """Run a task and return a structured result."""
