"""Resource visibility primitives for benchmark data routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping


ResourceVisibility = Literal["public", "evaluation_inputs", "hidden"]
Component = Literal["agent", "test_sandbox", "evaluator", "result"]
ResourceKind = Literal["text", "json", "file", "directory", "artifact", "scratch"]


VISIBILITIES = {"public", "evaluation_inputs", "hidden"}
COMPONENTS = {"agent", "test_sandbox", "evaluator", "result"}
RESOURCE_KINDS = {"text", "json", "file", "directory", "artifact", "scratch"}
COMPONENT_VISIBILITIES: dict[str, tuple[str, ...]] = {
    "agent": ("public",),
    "test_sandbox": ("public", "evaluation_inputs"),
    "evaluator": ("public", "hidden"),
    "result": ("public", "evaluation_inputs", "hidden"),
}
REDACTED = "<redacted>"


@dataclass(frozen=True)
class Resource:
    """One benchmark datum plus the visibility label assigned by an adapter."""

    name: str
    value: Any
    visibility: ResourceVisibility
    kind: ResourceKind = "json"

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("resource.name is required")
        if self.visibility not in VISIBILITIES:
            raise ValueError(f"resource.visibility must be one of {sorted(VISIBILITIES)}")
        if self.kind not in RESOURCE_KINDS:
            raise ValueError(f"resource.kind must be one of {sorted(RESOURCE_KINDS)}")


@dataclass(frozen=True)
class ComponentView:
    """Filtered view of resources for one framework component."""

    component: Component
    resources: tuple[Resource, ...] = ()
    redact_non_public: bool = False

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for resource in self.resources:
            if self.redact_non_public and resource.visibility != "public":
                payload[resource.name] = REDACTED
            else:
                payload[resource.name] = resource.value
        return payload

    def summary(self) -> list[dict[str, Any]]:
        summary = []
        for resource in self.resources:
            item: dict[str, Any] = {
                "name": resource.name,
                "visibility": resource.visibility,
                "kind": resource.kind,
            }
            if resource.visibility == "public":
                item["value"] = resource.value
            else:
                item["redacted"] = True
            summary.append(item)
        return summary


@dataclass(frozen=True)
class ResourceBundle:
    """Task-carried resource collection with component-safe views."""

    resources: Mapping[str, Resource] | Iterable[Resource] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "resources", _normalize_resources(self.resources))

    def by_visibility(self, visibility: ResourceVisibility) -> tuple[Resource, ...]:
        if visibility not in VISIBILITIES:
            raise ValueError(f"visibility must be one of {sorted(VISIBILITIES)}")
        return tuple(resource for resource in self.resources.values() if resource.visibility == visibility)

    def view_for(self, component: Component) -> ComponentView:
        if component not in COMPONENTS:
            raise ValueError(f"component must be one of {sorted(COMPONENTS)}")
        allowed = COMPONENT_VISIBILITIES[component]
        return ComponentView(
            component=component,
            resources=tuple(
                resource for resource in self.resources.values() if resource.visibility in allowed
            ),
            redact_non_public=component == "result",
        )

    def payload_for(self, component: Component) -> dict[str, Any]:
        return self.view_for(component).payload()

    def summary(self) -> list[dict[str, Any]]:
        return self.view_for("result").summary()

def public(name: str, value: Any) -> Resource:
    return Resource(name=name, value=value, visibility="public", kind=_kind_for_value(value))


def evaluation_input(name: str, value: Any) -> Resource:
    return Resource(
        name=name,
        value=value,
        visibility="evaluation_inputs",
        kind=_kind_for_value(value),
    )


def hidden(name: str, value: Any) -> Resource:
    return Resource(name=name, value=value, visibility="hidden", kind=_kind_for_value(value))


def _normalize_resources(resources: Mapping[str, Resource] | Iterable[Resource]) -> dict[str, Resource]:
    normalized: dict[str, Resource] = {}
    if isinstance(resources, Mapping):
        iterable = resources.values()
        for key, resource in resources.items():
            if not isinstance(resource, Resource):
                raise TypeError("ResourceBundle mapping values must be Resource instances")
            if key != resource.name:
                raise ValueError(f"resource key {key!r} does not match resource name {resource.name!r}")
    else:
        iterable = resources
    for resource in iterable:
        if not isinstance(resource, Resource):
            raise TypeError("ResourceBundle entries must be Resource instances")
        if resource.name in normalized:
            raise ValueError(f"duplicate resource name: {resource.name}")
        normalized[resource.name] = resource
    return normalized


def _kind_for_value(value: Any) -> ResourceKind:
    if isinstance(value, str):
        return "text"
    return "json"
