"""Normalized task models used by benchmark adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from securebench.resources import Component, Resource, ResourceBundle, ResourceKind


TaskType = Literal["multiple_choice", "code_generation", "github_patch"]
TaskSpec = dict[str, Any]


@dataclass(frozen=True)
class SecureBenchTask:
    """Base normalized task.

    Adapter instances may keep hidden evaluator data on these task objects, but
    only `agent_payload()` should be sent to the agent.
    """

    id: str
    benchmark_id: str
    task_type: TaskType
    metadata: dict[str, Any] = field(default_factory=dict)
    resources: ResourceBundle = field(default_factory=ResourceBundle)

    def agent_payload(self) -> dict[str, Any]:
        return self.public_payload()

    def public_payload(self) -> dict[str, Any]:
        return self.resources.payload_for("agent")

    def evaluation_payload(self) -> dict[str, Any]:
        return self.resources.payload_for("test_sandbox")

    def hidden_payload(self) -> dict[str, Any]:
        return self.resources.payload_for("evaluator")

    def view_for(self, component: Component):
        return self.resources.view_for(component)

    def resource_summary(self) -> list[dict[str, Any]]:
        return self.resources.summary()


def task_from_spec(spec: TaskSpec) -> SecureBenchTask:
    """Convert a plain normalized task spec into an internal task object."""
    if not isinstance(spec, dict):
        raise ValueError("task spec must be an object")

    task_id = _required_str(spec, "id", "task spec")
    benchmark_id = _required_str(spec, "benchmark_id", "task spec")
    task_type = _required_str(spec, "task_type", "task spec")
    metadata = spec.get("metadata", {})
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("task spec metadata must be an object")

    resources = _resources_from_spec(_required_dict(spec, "resources", "task spec"))
    values = {name: resource.value for name, resource in resources.resources.items()}

    if task_type == "multiple_choice":
        _require_resources(values, task_type, ("question", "choices", "answer"))
        return MultipleChoiceTask(
            id=task_id,
            benchmark_id=benchmark_id,
            task_type="multiple_choice",
            metadata=metadata,
            resources=resources,
            question=values["question"],
            choices=tuple(values["choices"]),
            answer=values["answer"],
            subject=values.get("subject"),
        )

    if task_type == "code_generation":
        _require_resources(values, task_type, ("prompt",))
        return CodeGenerationTask(
            id=task_id,
            benchmark_id=benchmark_id,
            task_type="code_generation",
            metadata=metadata,
            resources=resources,
            prompt=values["prompt"],
            language=values.get("language", "python"),
            entry_point=values.get("entry_point"),
            tests=values.get("tests"),
            canonical_solution=values.get("canonical_solution"),
        )

    if task_type == "github_patch":
        _require_resources(values, task_type, ("repo", "base_commit", "instructions"))
        return GitHubPatchTask(
            id=task_id,
            benchmark_id=benchmark_id,
            task_type="github_patch",
            metadata=metadata,
            resources=resources,
            repo=values["repo"],
            base_commit=values["base_commit"],
            instructions=values["instructions"],
            hints_text=values.get("hints_text", ""),
            version=values.get("version"),
            environment_setup_commit=values.get("environment_setup_commit"),
            fail_to_pass=_tuple_of_str(values.get("fail_to_pass", ())),
            pass_to_pass=_tuple_of_str(values.get("pass_to_pass", ())),
            gold_patch=values.get("gold_patch"),
            test_patch=values.get("test_patch"),
            test_groups=_test_groups(values.get("test_groups", {})),
            hidden_patches=dict(values.get("hidden_patches", {})),
        )

    raise ValueError(f"unknown task_type {task_type!r}")


@dataclass(frozen=True)
class MultipleChoiceTask(SecureBenchTask):
    question: str = ""
    choices: tuple[str, ...] = ()
    answer: int | str | None = None
    subject: str | None = None


@dataclass(frozen=True)
class CodeGenerationTask(SecureBenchTask):
    prompt: str = ""
    language: str = "python"
    entry_point: str | None = None
    tests: str | None = None
    canonical_solution: str | None = None


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


def _resources_from_spec(resources_data: dict[str, Any]) -> ResourceBundle:
    resources: list[Resource] = []
    for name, resource_data in resources_data.items():
        if not isinstance(name, str) or not name:
            raise ValueError("resource names must be non-empty strings")
        if not isinstance(resource_data, dict):
            raise ValueError(f"resource {name!r} must be an object")
        if "value" not in resource_data:
            raise ValueError(f"resource {name!r} requires value")
        visibility = _required_str(resource_data, "visibility", f"resource {name!r}")
        if "expose" in resource_data:
            raise ValueError(f"resource {name!r} uses removed field 'expose'")
        value = resource_data["value"]
        resources.append(
            Resource(name=name, value=value, visibility=visibility, kind=_resource_kind(value))  # type: ignore[arg-type]
        )
    return ResourceBundle(resources)


def _required_dict(data: dict[str, Any], key: str, context: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{context} requires object field {key!r}")
    return value


def _required_str(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} requires string field {key!r}")
    return value


def _require_resources(values: dict[str, Any], task_type: str, names: tuple[str, ...]) -> None:
    missing = [name for name in names if name not in values]
    if missing:
        raise ValueError(f"{task_type} task spec missing required resources: {missing}")


def _tuple_of_str(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return (str(value),)


def _test_groups(value: Any) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("github_patch test_groups resource must be an object")
    return {str(name): _tuple_of_str(tests) for name, tests in value.items()}


def _resource_kind(value: Any) -> ResourceKind:
    if isinstance(value, str):
        return "text"
    return "json"
