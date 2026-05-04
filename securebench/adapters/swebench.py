"""Adapter for SWE-bench Verified rows."""

from __future__ import annotations

import json
from typing import Any

from securebench.adapters.base import BenchmarkAdapter
from securebench.tasks import GitHubPatchTask


class SWEBenchVerifiedAdapter(BenchmarkAdapter):
    benchmark_id = "swebench_verified"
    task_type = "github_patch"

    def to_task(self, row: dict[str, Any], **context: Any) -> GitHubPatchTask:
        fail_to_pass = _coerce_test_list(row.get("FAIL_TO_PASS", ()))
        pass_to_pass = _coerce_test_list(row.get("PASS_TO_PASS", ()))
        test_patch = row.get("test_patch")
        return GitHubPatchTask(
            id=row["instance_id"],
            benchmark_id=self.benchmark_id,
            task_type="github_patch",
            repo=row["repo"],
            base_commit=row["base_commit"],
            instructions=row["problem_statement"],
            hints_text=row.get("hints_text", ""),
            version=row.get("version"),
            environment_setup_commit=row.get("environment_setup_commit"),
            fail_to_pass=fail_to_pass,
            pass_to_pass=pass_to_pass,
            gold_patch=row.get("patch"),
            test_patch=test_patch,
            test_groups={
                "fail_to_pass": fail_to_pass,
                "pass_to_pass": pass_to_pass,
            },
            hidden_patches={} if test_patch is None else {"tests": str(test_patch)},
            hidden_fields=("patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS"),
            metadata={
                "split": context.get("split", "test"),
                "difficulty": row.get("difficulty"),
                "created_at": row.get("created_at"),
            },
        )

    def format_prediction(
        self,
        task: GitHubPatchTask,
        model_patch: str,
        *,
        model_name_or_path: str = "securebench-agent",
    ) -> dict[str, str]:
        """Return one SWE-bench-compatible prediction JSON object."""
        return {
            "instance_id": task.id,
            "model_name_or_path": model_name_or_path,
            "model_patch": model_patch,
        }


def _coerce_test_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return ()
        try:
            loaded = json.loads(stripped)
        except json.JSONDecodeError:
            return (stripped,)
        if isinstance(loaded, list):
            return tuple(str(item) for item in loaded)
        return (str(loaded),)
    return (str(value),)
