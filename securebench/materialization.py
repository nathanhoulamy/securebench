"""Internal resource materialization primitives."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal, Protocol

from securebench.path_policy import validate_materialization_plan
from securebench.resources import Component, Resource, ResourceBundle, ResourceKind, ResourceVisibility

if TYPE_CHECKING:
    from securebench.sandboxes import DockerBindMount


MaterializationComponent = Literal["agent", "test_sandbox", "evaluator"]
SerializationFormat = Literal["json", "copy"]
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
    read_only: bool = False


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


class VisibilityAwareMaterializer:
    """Materialize compiled tasks across public, evaluation, and hidden lanes."""

    def build_plan(self, source: Any, component: Component) -> MaterializationPlan:
        """Return value-backed and file-backed resources for one component."""
        target_component = _materialization_component(component)
        bundle = _resource_bundle(source)

        planned: list[MaterializedResource] = []
        for resource in bundle.view_for(target_component).resources:
            if resource.name == "assets" and resource.visibility == "public":
                if target_component in ("agent", "test_sandbox"):
                    planned.extend(_public_asset_resources(source, resource.value, target_component))
                continue
            if resource.visibility in ("evaluation_inputs", "hidden") and _is_file_reference(resource.value):
                planned.append(_file_reference_resource(source, resource, target_component))
                continue
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
        source: Any,
        target: MaterializationTarget,
        component: Component,
    ) -> MaterializationPlan:
        """Write value-backed resources and copy file-backed resources."""
        target_component = _materialization_component(component)
        bundle = _resource_bundle(source)
        plan = self.build_plan(source, target_component)

        for item in plan.resources:
            if item.serialization == "copy":
                _copy_materialized_resource(item, target)
            else:
                resource = bundle.resources[item.name]
                target.write_file(item.relative_path, _serialize_json(resource.value))
        return plan


def docker_read_only_mounts(plan: MaterializationPlan, workspace_root: str | Path) -> tuple[DockerBindMount, ...]:
    """Return Docker bind mounts for read-only copied resources in a plan."""
    from securebench.sandboxes import DockerBindMount

    root = Path(workspace_root)
    mounts = []
    for item in plan.resources:
        if item.serialization == "copy" and item.read_only:
            mounts.append(
                DockerBindMount(
                    source=root.joinpath(*PurePosixPath(item.relative_path).parts),
                    target=item.relative_path,
                    read_only=True,
                )
            )
    return tuple(mounts)


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


def _public_asset_resources(source: Any, value: Any, component: MaterializationComponent) -> tuple[MaterializedResource, ...]:
    if not isinstance(value, list):
        raise MaterializationError("assets resource must be a list")
    default_read_only = _asset_default_read_only(source)
    planned = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise MaterializationError(f"assets[{index}] must be an object")
        asset_path = _required_path_value(item.get("path"), f"assets[{index}].path")
        mount_path = _required_path_value(item.get("mount", asset_path), f"assets[{index}].mount")
        read_only = _optional_bool(item.get("read_only"), default_read_only, f"assets[{index}].read_only")
        source_path = _resolve_asset_source(source, "public", asset_path)
        kind = _source_kind(source_path, f"assets[{index}]")
        planned.append(
            MaterializedResource(
                name=f"assets[{index}]",
                visibility="public",
                kind=kind,
                component=component,
                relative_path=mount_path,
                serialization="copy",
                placement="workspace",
                source_path=str(source_path),
                read_only=read_only,
            )
        )
    return tuple(planned)


def _file_reference_resource(source: Any, resource: Resource, component: MaterializationComponent) -> MaterializedResource:
    if not isinstance(resource.value, dict):
        raise MaterializationError(f"resource {resource.name!r} file reference must be an object")
    source_path_value = _required_path_value(resource.value.get("path"), f"resource {resource.name!r}.path")
    source_path = _resolve_asset_source(source, "eval", source_path_value)
    kind = _source_kind(source_path, f"resource {resource.name!r}")
    default_mount = _non_public_default_mount(resource.visibility, source_path_value)
    mount_path = _required_path_value(resource.value.get("mount", default_mount), f"resource {resource.name!r}.mount")
    _validate_non_public_mount(resource.visibility, mount_path, resource.name)
    return MaterializedResource(
        name=resource.name,
        visibility=resource.visibility,
        kind=kind,
        component=component,
        relative_path=mount_path,
        serialization="copy",
        placement="internal",
        source_path=str(source_path),
        read_only=_optional_bool(resource.value.get("read_only"), True, f"resource {resource.name!r}.read_only"),
    )


def _is_file_reference(value: Any) -> bool:
    return isinstance(value, dict) and "path" in value and set(value) <= {"path", "mount", "read_only"}


def _manifest_dir(source: Any) -> Path:
    metadata = getattr(source, "metadata", None)
    if not isinstance(metadata, dict):
        raise MaterializationError("task metadata is required to materialize file assets")
    pack = metadata.get("benchmark_pack")
    if not isinstance(pack, dict):
        raise MaterializationError("task metadata benchmark_pack is required to materialize file assets")
    manifest_path = pack.get("manifest_path")
    if not isinstance(manifest_path, str) or not manifest_path:
        raise MaterializationError("task metadata benchmark_pack.manifest_path is required to materialize file assets")
    return Path(manifest_path).parent.resolve()


def _asset_root(source: Any, root_name: Literal["public", "eval"]) -> Path:
    metadata = getattr(source, "metadata", {})
    roots = metadata.get("asset_roots") if isinstance(metadata, dict) else None
    root_value = roots.get(root_name) if isinstance(roots, dict) else None
    if root_value is None:
        root_value = "assets/" if root_name == "public" else "hidden/"
    root_path = _required_path_value(root_value, f"asset_roots.{root_name}")
    manifest_dir = _manifest_dir(source)
    root = (manifest_dir / root_path).resolve()
    if not root.is_relative_to(manifest_dir):
        raise MaterializationError(f"asset_roots.{root_name} may not resolve outside the benchmark package")
    return root


def _resolve_asset_source(source: Any, root_name: Literal["public", "eval"], path: str) -> Path:
    root = _asset_root(source, root_name)
    candidate = root / path
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise MaterializationError(f"asset source escapes {root_name} asset root: {path}")
    if not candidate.exists():
        raise MaterializationError(f"asset source does not exist: {path}")
    return candidate


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


def _copy_materialized_resource(item: MaterializedResource, target: MaterializationTarget) -> None:
    if item.source_path is None:
        raise MaterializationError(f"copy resource {item.name!r} requires source_path")
    source = Path(item.source_path)
    if item.kind == "file":
        target.write_file(item.relative_path, source.read_bytes())
        return
    if item.kind == "directory":
        for child in sorted(source.rglob("*")):
            if child.is_file():
                relative_child = PurePosixPath(child.relative_to(source).as_posix())
                target.write_file(PurePosixPath(item.relative_path) / relative_child, child.read_bytes())
        return
    raise MaterializationError(f"copy resource {item.name!r} must be a file or directory")


def _asset_default_read_only(source: Any) -> bool:
    metadata = getattr(source, "metadata", {})
    defaults = metadata.get("asset_defaults") if isinstance(metadata, dict) else None
    value = defaults.get("read_only") if isinstance(defaults, dict) else True
    if not isinstance(value, bool):
        raise MaterializationError("task metadata asset_defaults.read_only must be a boolean")
    return value


def _required_path_value(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MaterializationError(f"{field} must be a non-empty relative path")
    if "\\" in value:
        raise MaterializationError(f"{field} may not contain backslashes")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise MaterializationError(f"{field} may not be absolute")
    if ".." in path.parts:
        raise MaterializationError(f"{field} may not contain '..'")
    if str(path) in ("", "."):
        raise MaterializationError(f"{field} must be a non-empty relative path")
    return str(path)


def _optional_bool(value: Any, default: bool, field: str) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise MaterializationError(f"{field} must be a boolean")
    return value


def _non_public_default_mount(visibility: ResourceVisibility, path: str) -> str:
    if visibility == "evaluation_inputs":
        return str(PurePosixPath("securebench") / "evaluation_inputs" / path)
    if visibility == "hidden":
        return str(PurePosixPath("securebench") / "evaluator" / path)
    raise MaterializationError(f"file reference visibility is not non-public: {visibility!r}")


def _validate_non_public_mount(visibility: ResourceVisibility, mount_path: str, resource_name: str) -> None:
    if visibility == "evaluation_inputs":
        root = PurePosixPath("securebench") / "evaluation_inputs"
    elif visibility == "hidden":
        root = PurePosixPath("securebench") / "evaluator"
    else:
        raise MaterializationError(f"resource {resource_name!r} has unsupported file-reference visibility")
    candidate = PurePosixPath(mount_path)
    if not (candidate == root or candidate.is_relative_to(root)):
        raise MaterializationError(f"resource {resource_name!r}.mount must be under {root}")


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
