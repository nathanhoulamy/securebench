"""Base interface for converting benchmark rows into SecureBench tasks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from securebench.tasks import SecureBenchTask, TaskSpec, task_from_spec


def resources_from_values(
    values: dict[str, Any],
    visibility: dict[str, str],
    *,
    drop_empty: bool = False,
) -> dict[str, dict[str, Any]]:
    """Build a normalized resource mapping from values and visibility labels."""
    omitted = (None, "", (), [], {}) if drop_empty else (None,)
    return {
        name: {"value": value, "visibility": visibility[name]}
        for name, value in values.items()
        if name in visibility and value not in omitted
    }


class BenchmarkAdapter(ABC):
    """Translate one benchmark's raw rows into normalized SecureBench tasks.

    Adapters are the benchmark-specific classification boundary. They map
    native row fields into plain task specs with visibility labels; SecureBench
    then converts those specs into internal task/resource objects.
    """

    benchmark_id: str
    task_type: str

    @abstractmethod
    def to_task_spec(self, row: dict[str, Any], **context: Any) -> TaskSpec:
        """Convert a raw dataset row into a plain normalized task spec."""

    def to_task(self, row: dict[str, Any], **context: Any) -> SecureBenchTask:
        """Convert a raw dataset row into an internal SecureBench task."""
        return task_from_spec(self.to_task_spec(row, **context))

    def agent_payload(self, row: dict[str, Any], **context: Any) -> dict[str, Any]:
        """Return only the task data that is safe to show to the agent."""
        return self.to_task(row, **context).agent_payload()
