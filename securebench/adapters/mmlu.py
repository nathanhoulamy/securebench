"""Adapter for MMLU-style multiple-choice rows."""

from __future__ import annotations

from typing import Any

from securebench.adapters.base import BenchmarkAdapter
from securebench.tasks import TaskSpec


class MMLUAdapter(BenchmarkAdapter):
    benchmark_id = "mmlu"
    task_type = "multiple_choice"

    def to_task_spec(self, row: dict[str, Any], **context: Any) -> TaskSpec:
        config = context.get("config") or row.get("subject") or "unknown"
        split = context.get("split", "test")
        row_idx = context.get("row_idx")
        task_id = context.get("id") or f"mmlu/{config}/{split}/{row_idx}"
        choices = tuple(row["choices"])
        answer = row.get("answer")
        subject = row.get("subject")
        resource_values = {
            "question": row["question"],
            "choices": list(choices),
            "answer": answer,
            "subject": subject,
        }
        resource_visibility = {
            "question": "public",
            "choices": "public",
            "answer": "hidden",
            "subject": "public",
        }

        return {
            "id": task_id,
            "benchmark_id": self.benchmark_id,
            "task_type": "multiple_choice",
            "resources": _resources(resource_values, resource_visibility),
            "metadata": {
                "config": config,
                "split": split,
                "row_idx": row_idx,
            },
        }


def _resources(values: dict[str, Any], visibility: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {
        name: {"value": value, "visibility": visibility[name]}
        for name, value in values.items()
        if name in visibility and value is not None
    }
