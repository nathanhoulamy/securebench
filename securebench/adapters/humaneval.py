"""Adapter for OpenAI HumanEval rows."""

from __future__ import annotations

from typing import Any

from securebench.adapters.base import BenchmarkAdapter
from securebench.tasks import CodeGenerationTask


class HumanEvalAdapter(BenchmarkAdapter):
    benchmark_id = "humaneval"
    task_type = "code_generation"

    def to_task(self, row: dict[str, Any], **context: Any) -> CodeGenerationTask:
        return CodeGenerationTask(
            id=row["task_id"],
            benchmark_id=self.benchmark_id,
            task_type="code_generation",
            prompt=row["prompt"],
            language="python",
            entry_point=row.get("entry_point"),
            tests=row.get("test"),
            canonical_solution=row.get("canonical_solution"),
            hidden_fields=("canonical_solution", "test"),
            metadata={
                "split": context.get("split", "test"),
            },
        )

