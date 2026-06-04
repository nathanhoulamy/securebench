"""Normalized task models used by benchmark-pack compilation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from securebench.resources import Component, Resource, ResourceBundle, ResourceKind


TaskType = str
TaskSpec = dict[str, Any]


@dataclass(frozen=True)
class SecureBenchTask:
    """Base normalized task.

    Compiled tasks may keep hidden evaluator data on these objects, but only
    `agent_payload()` should be sent to a candidate-producing harness.
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
    return SecureBenchTask(
        id=task_id,
        benchmark_id=benchmark_id,
        task_type=task_type,
        metadata=metadata,
        resources=resources,
    )

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


def resource_value(task: SecureBenchTask, name: str, default: Any = None) -> Any:
    resource = task.resources.resources.get(name)
    if resource is None:
        return default
    return resource.value


def resource_text(task: SecureBenchTask, name: str, default: str = "") -> str:
    return str(resource_value(task, name, default))


def _resource_kind(value: Any) -> ResourceKind:
    if isinstance(value, str):
        return "text"
    return "json"
