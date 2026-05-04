"""Base interface for converting benchmark rows into SecureBench tasks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from securebench.tasks import SecureBenchTask


class BenchmarkAdapter(ABC):
    """Translate one benchmark's raw rows into normalized SecureBench tasks."""

    benchmark_id: str
    task_type: str

    @abstractmethod
    def to_task(self, row: dict[str, Any], **context: Any) -> SecureBenchTask:
        """Convert a raw dataset row into a normalized task."""

    def agent_payload(self, row: dict[str, Any], **context: Any) -> dict[str, Any]:
        """Return only the task data that is safe to show to the agent."""
        return self.to_task(row, **context).agent_payload()

