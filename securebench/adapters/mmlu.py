"""Adapter for MMLU-style multiple-choice rows."""

from __future__ import annotations

from typing import Any

from securebench.adapters.base import BenchmarkAdapter
from securebench.tasks import MultipleChoiceTask


class MMLUAdapter(BenchmarkAdapter):
    benchmark_id = "mmlu"
    task_type = "multiple_choice"

    def to_task(self, row: dict[str, Any], **context: Any) -> MultipleChoiceTask:
        config = context.get("config") or row.get("subject") or "unknown"
        split = context.get("split", "test")
        row_idx = context.get("row_idx")
        task_id = context.get("id") or f"mmlu/{config}/{split}/{row_idx}"

        return MultipleChoiceTask(
            id=task_id,
            benchmark_id=self.benchmark_id,
            task_type="multiple_choice",
            question=row["question"],
            choices=tuple(row["choices"]),
            answer=row.get("answer"),
            subject=row.get("subject"),
            hidden_fields=("answer",),
            metadata={
                "config": config,
                "split": split,
                "row_idx": row_idx,
            },
        )
