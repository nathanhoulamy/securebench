"""Internal resource materialization primitives."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal, Protocol

from securebench.path_policy import validate_materialization_plan
from securebench.resources import Component, Resource, ResourceBundle, ResourceKind, ResourceVisibility


MaterializationComponent = Literal["agent", "test_sandbox", "evaluator"]
SerializationFormat = Literal["json"]

SUPPORTED_MATERIALIZATION_KINDS = {"text", "json"}


class MaterializationError(ValueError):
    """Raised when a resource cannot be materialized safely."""


class MaterializationTarget(Protocol):
    """Minimal file-writing interface needed for materialization."""

    def write_file(self, path: str | PurePosixPath, content: str | bytes) -> None:
        """Write content to the target."""


@dataclass(frozen=True)
class MaterializedResource:
    """One resource planned for a framework-owned materialized path."""

    name: str
    visibility: ResourceVisibility
    kind: ResourceKind
    component: MaterializationComponent
    relative_path: str
    serialization: SerializationFormat = "json"


@dataclass(frozen=True)
class MaterializationPlan:
    """Materialized resource plan for one target component."""

    component: MaterializationComponent
    resources: tuple[MaterializedResource, ...]


class ResourceMaterializer:
    """Build and write framework-owned resource materialization plans."""

    def build_plan(self, source: ResourceBundle | Any, component: Component) -> MaterializationPlan:
        """Return the resources and paths that would be materialized."""
        target_component = _materialization_component(component)
        bundle = _resource_bundle(source)

        planned = []
        for resource in bundle.view_for(target_component).resources:
            _validate_materializable_resource(resource)
            planned.append(
                MaterializedResource(
                    name=resource.name,
                    visibility=resource.visibility,
                    kind=resource.kind,
                    component=target_component,
                    relative_path=_resource_path(resource, target_component),
                )
            )
        plan = MaterializationPlan(component=target_component, resources=tuple(planned))
        validate_materialization_plan(plan)
        return plan

    def materialize(
        self,
        source: ResourceBundle | Any,
        target: MaterializationTarget,
        component: Component,
    ) -> MaterializationPlan:
        """Write materialized resource files and return the applied plan."""
        target_component = _materialization_component(component)
        bundle = _resource_bundle(source)
        plan = self.build_plan(bundle, target_component)

        for item in plan.resources:
            resource = bundle.resources[item.name]
            target.write_file(item.relative_path, _serialize_json(resource.value))
        return plan


def _materialization_component(component: Component) -> MaterializationComponent:
    if component == "result":
        raise MaterializationError("result is not a materialization target")
    if component not in ("agent", "test_sandbox", "evaluator"):
        raise MaterializationError(f"unsupported materialization component: {component!r}")
    return component


def _resource_bundle(source: ResourceBundle | Any) -> ResourceBundle:
    if isinstance(source, ResourceBundle):
        return source
    resources = getattr(source, "resources", None)
    if isinstance(resources, ResourceBundle):
        return resources
    raise TypeError("materialization source must be a ResourceBundle or task with ResourceBundle resources")


def _validate_materializable_resource(resource: Resource) -> None:
    if resource.kind not in SUPPORTED_MATERIALIZATION_KINDS:
        raise MaterializationError(f"resource kind {resource.kind!r} is not supported for materialization")
    _safe_resource_name(resource.name)
    _serialize_json(resource.value)


def _resource_path(resource: Resource, component: MaterializationComponent) -> str:
    safe_name = _safe_resource_name(resource.name)
    if component == "evaluator":
        path = PurePosixPath("securebench") / "evaluator" / f"{safe_name}.json"
    elif resource.visibility == "evaluation_inputs":
        path = PurePosixPath("securebench") / "evaluation_inputs" / f"{safe_name}.json"
    else:
        path = PurePosixPath("securebench") / "public" / f"{safe_name}.json"
    _validate_generated_path(path)
    return str(path)


def _safe_resource_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise MaterializationError("resource name must be a non-empty string")
    if name.startswith(("/", "\\")) or PurePosixPath(name).is_absolute():
        raise MaterializationError(f"resource name may not be absolute: {name!r}")
    if "/" in name or "\\" in name:
        raise MaterializationError(f"resource name may not contain path separators: {name!r}")
    if ".." in name:
        raise MaterializationError(f"resource name may not contain '..': {name!r}")
    return name


def _validate_generated_path(path: PurePosixPath) -> None:
    root = PurePosixPath("securebench")
    if path.is_absolute() or ".." in path.parts or not path.is_relative_to(root):
        raise MaterializationError(f"materialized path escapes root: {path}")


def _serialize_json(value: Any) -> str:
    try:
        return json.dumps(value, indent=2, sort_keys=True) + "\n"
    except (TypeError, ValueError) as exc:
        raise MaterializationError(f"resource value is not JSON serializable: {exc}") from exc
