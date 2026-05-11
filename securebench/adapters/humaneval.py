"""Adapter for OpenAI HumanEval rows."""

from __future__ import annotations

from typing import Any

from securebench.adapters.base import BenchmarkAdapter, resources_from_values
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
            "resources": resources_from_values(resource_values, resource_visibility),
            "metadata": {
                "split": context.get("split", "test"),
            },
        }
