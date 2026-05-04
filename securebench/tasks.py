"""Normalized task models used by benchmark adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


TaskType = Literal["multiple_choice", "code_generation", "github_patch"]


@dataclass(frozen=True)
class SecureBenchTask:
    """Base normalized task.

    Adapter instances may keep hidden evaluator data on these task objects, but
    only `agent_payload()` should be sent to the agent.
    """

    id: str
    benchmark_id: str
    task_type: TaskType
    hidden_fields: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def agent_payload(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class MultipleChoiceTask(SecureBenchTask):
    question: str = ""
    choices: tuple[str, ...] = ()
    answer: int | str | None = None
    subject: str | None = None

    def agent_payload(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "choices": list(self.choices),
        }


@dataclass(frozen=True)
class CodeGenerationTask(SecureBenchTask):
    prompt: str = ""
    language: str = "python"
    entry_point: str | None = None
    tests: str | None = None
    canonical_solution: str | None = None

    def agent_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "prompt": self.prompt,
            "language": self.language,
        }
        if self.entry_point is not None:
            payload["entry_point"] = self.entry_point
        return payload


@dataclass(frozen=True)
class GitHubPatchTask(SecureBenchTask):
    repo: str = ""
    base_commit: str = ""
    instructions: str = ""
    hints_text: str = ""
    version: str | None = None
    environment_setup_commit: str | None = None
    fail_to_pass: tuple[str, ...] = ()
    pass_to_pass: tuple[str, ...] = ()
    gold_patch: str | None = None
    test_patch: str | None = None
    test_groups: dict[str, tuple[str, ...]] = field(default_factory=dict)
    hidden_patches: dict[str, str] = field(default_factory=dict)

    def agent_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "repo": self.repo,
            "base_commit": self.base_commit,
            "instructions": self.instructions,
        }
        if self.hints_text:
            payload["hints_text"] = self.hints_text
        if self.version is not None:
            payload["version"] = self.version
        return payload
