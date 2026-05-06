"""Adapter for OpenAI HumanEval rows."""

from __future__ import annotations

from typing import Any

from securebench.adapters.base import BenchmarkAdapter
from securebench.tasks import TaskSpec


class HumanEvalAdapter(BenchmarkAdapter):
    benchmark_id = "humaneval"
    task_type = "code_generation"

    def to_task_spec(self, row: dict[str, Any], **context: Any) -> TaskSpec:
        entry_point = row.get("entry_point")
        tests = row.get("test")
        canonical_solution = row.get("canonical_solution")
        resource_values = {
            "prompt": row["prompt"],
            "language": "python",
            "entry_point": entry_point,
            "tests": tests,
            "canonical_solution": canonical_solution,
        }
        resource_visibility = {
            "prompt": "public",
            "language": "public",
            "entry_point": "public",
            "tests": "hidden",
            "canonical_solution": "hidden",
        }

        return {
            "id": row["task_id"],
            "benchmark_id": self.benchmark_id,
            "task_type": "code_generation",
            "resources": _resources(resource_values, resource_visibility),
            "metadata": {
                "split": context.get("split", "test"),
            },
        }


def _resources(values: dict[str, Any], visibility: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {
        name: {"value": value, "visibility": visibility[name]}
        for name, value in values.items()
        if name in visibility and value is not None
    }
