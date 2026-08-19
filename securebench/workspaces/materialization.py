"""Internal resource materialization primitives."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal, Protocol

from securebench.workspaces.path_policy import validate_materialization_plan
from securebench.resources import Component, Resource, ResourceBundle, ResourceKind, ResourceVisibility

if TYPE_CHECKING:
    from securebench.sandboxes import DockerBindMount


MaterializationComponent = Literal["agent", "evaluation_runtime", "oracle"]
SerializationFormat = Literal["json", "mount"]
MaterializationPlacement = Literal["internal", "workspace"]

SUPPORTED_MATERIALIZATION_KINDS = {"text", "json"}


class MaterializationError(ValueError):
    """Raised when a resource cannot be materialized safely."""


class MaterializationTarget(Protocol):
    """Minimal file-writing interface needed for materialization."""

    def write_file(self, path: str | PurePosixPath, content: str | bytes) -> None:
        """Write content to the target."""


@dataclass(frozen=True)
class MaterializedResource:
    """One resource planned for a materialized path."""

    name: str
    visibility: ResourceVisibility
    kind: ResourceKind
    component: MaterializationComponent
    relative_path: str
    serialization: SerializationFormat = "json"
    placement: MaterializationPlacement = "internal"
    source_path: str | None = None
    container_path: str | None = None
    read_only: bool = False


@dataclass(frozen=True)
class MaterializationPlan:
    """Materialized resource plan for one target component."""

    component: MaterializationComponent
    resources: tuple[MaterializedResource, ...]


class VisibilityAwareMaterializer:
    """Materialize compiled tasks across public, evaluation, and hidden lanes."""

    def build_plan(self, source: Any, component: Component) -> MaterializationPlan:
        """Return value-backed and file-backed resources for one component."""
        target_component = _materialization_component(component)
        bundle = _resource_bundle(source)

        planned: list[MaterializedResource] = []
        for resource in bundle.view_for(target_component).resources:
            if resource.kind in ("file", "directory"):
                # Host resources are consumed by trusted host code directly;
                # they are never copied into a candidate-accessible workspace.
                if target_component == "oracle":
                    continue
                planned.append(_compiled_file_resource(resource, target_component))
                continue
            _validate_materializable_resource(resource)
            planned.append(
                MaterializedResource(
                    name=resource.name,
                    visibility=resource.visibility,
                    kind=resource.kind,
                    component=target_component,
                    relative_path=_resource_path(resource, target_component),
                    read_only=_resource_default_read_only(resource, target_component),
                )
            )

        plan = MaterializationPlan(component=target_component, resources=tuple(planned))
        validate_materialization_plan(plan)
        return plan

    def materialize(
        self,
        source: Any,
        target: MaterializationTarget,
        component: Component,
    ) -> MaterializationPlan:
        """Write value-backed resources; file resources remain explicit mounts."""
        target_component = _materialization_component(component)
        bundle = _resource_bundle(source)
        plan = self.build_plan(source, target_component)

        for item in plan.resources:
            if item.serialization == "json":
                resource = bundle.resources[item.name]
                _write_materialized_file(item, target, _serialize_json(resource.value))
        return plan


def docker_resource_mounts(plan: MaterializationPlan) -> tuple[DockerBindMount, ...]:
    """Return explicit Docker mounts for compiled file resources."""
    from securebench.sandboxes import DockerBindMount

    mounts = []
    for item in plan.resources:
        if item.container_path is not None:
            if item.source_path is None:
                raise MaterializationError(f"mounted resource {item.name!r} has no source path")
            mounts.append(
                DockerBindMount(
                    source=item.source_path,
                    target=item.container_path,
                    read_only=item.read_only,
                )
            )
    return tuple(mounts)


def _materialization_component(component: Component) -> MaterializationComponent:
    if component == "result":
        raise MaterializationError("result is not a materialization target")
    if component not in ("agent", "evaluation_runtime", "oracle"):
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


def _resource_default_read_only(resource: Resource, component: MaterializationComponent) -> bool:
    return component in ("evaluation_runtime", "oracle") and resource.visibility in (
        "evaluation_inputs",
        "hidden",
    )


def _resource_path(resource: Resource, component: MaterializationComponent) -> str:
    safe_name = _safe_resource_name(resource.name)
    if component == "oracle":
        path = PurePosixPath("securebench") / "oracle" / f"{safe_name}.json"
    elif resource.visibility == "evaluation_inputs":
        path = PurePosixPath("securebench") / "evaluation_inputs" / f"{safe_name}.json"
    else:
        path = PurePosixPath("securebench") / "public" / f"{safe_name}.json"
    _validate_generated_path(path)
    return str(path)


def _compiled_file_resource(
    resource: Resource,
    component: MaterializationComponent,
) -> MaterializedResource:
    if not isinstance(resource.value, dict):
        raise MaterializationError(f"resource {resource.name!r} file descriptor must be an object")
    source_value = resource.value.get("source_path")
    mount_value = resource.value.get("mount")
    read_only = resource.value.get("read_only", True)
    if not isinstance(source_value, str) or not source_value:
        raise MaterializationError(f"resource {resource.name!r}.source_path is required")
    source = Path(source_value)
    if not source.is_absolute() or source.is_symlink():
        raise MaterializationError(f"resource {resource.name!r}.source_path is not a safe resolved path")
    actual_kind = _source_kind(source, f"resource {resource.name!r}")
    if actual_kind != resource.kind:
        raise MaterializationError(f"resource {resource.name!r} changed kind after compilation")
    if not isinstance(mount_value, str) or not mount_value:
        raise MaterializationError(f"resource {resource.name!r}.mount is required")
    mount = PurePosixPath(mount_value)
    if not mount.is_absolute() or ".." in mount.parts or "\\" in mount_value:
        raise MaterializationError(f"resource {resource.name!r}.mount must be an absolute safe path")
    if not isinstance(read_only, bool):
        raise MaterializationError(f"resource {resource.name!r}.read_only must be a boolean")
    if not read_only:
        raise MaterializationError(
            f"resource {resource.name!r} requests a writable mount, but direct pack-source "
            "mounts must be read-only"
        )
    lane = "evaluation_inputs" if resource.visibility == "evaluation_inputs" else "public"
    staging = PurePosixPath("securebench") / lane / "files" / _safe_resource_name(resource.name)
    return MaterializedResource(
        name=resource.name,
        visibility=resource.visibility,
        kind=resource.kind,
        component=component,
        relative_path=str(staging),
        serialization="mount",
        placement="internal",
        source_path=str(source),
        container_path=str(mount),
        read_only=read_only,
    )


def _source_kind(path: Path, field: str) -> ResourceKind:
    if path.is_symlink():
        raise MaterializationError(f"{field} source may not be a symlink")
    if path.is_file():
        return "file"
    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_symlink():
                raise MaterializationError(f"{field} source directory may not contain symlinks")
        return "directory"
    raise MaterializationError(f"{field} source must be a file or directory")


def _write_materialized_file(item: MaterializedResource, target: MaterializationTarget, content: str | bytes) -> None:
    _reject_existing_non_public_target(item, target)
    _remove_existing_public_target(item, target)
    target.write_file(item.relative_path, content)


def _remove_existing_public_target(item: MaterializedResource, target: MaterializationTarget) -> None:
    if item.visibility != "public":
        return
    root = getattr(target, "root", None)
    if root is None:
        return
    relative_path = PurePosixPath(item.relative_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise MaterializationError(f"materialized path escapes root: {item.relative_path}")
    host_path = Path(root).joinpath(*relative_path.parts)
    root_resolved = Path(root).resolve()
    if not host_path.parent.resolve().is_relative_to(root_resolved):
        raise MaterializationError(f"materialized path escapes root: {item.relative_path}")
    if host_path.is_symlink() or host_path.is_file():
        host_path.unlink()
    elif host_path.exists():
        shutil.rmtree(host_path)


def _reject_existing_non_public_target(item: MaterializedResource, target: MaterializationTarget) -> None:
    if item.visibility not in ("evaluation_inputs", "hidden"):
        return
    root = getattr(target, "root", None)
    if root is None:
        return
    relative_path = PurePosixPath(item.relative_path)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise MaterializationError(f"materialized path escapes root: {item.relative_path}")
    host_path = Path(root).joinpath(*relative_path.parts)
    if host_path.exists() or host_path.is_symlink():
        raise MaterializationError(
            f"non-public materialized target already exists and will not be overwritten: {item.relative_path}"
        )


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
        return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    except (TypeError, ValueError) as exc:
        raise MaterializationError(f"resource value is not JSON serializable: {exc}") from exc
