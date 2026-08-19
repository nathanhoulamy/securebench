"""Workspace materialization and path-policy helpers."""

from securebench.workspaces.materialization import (
    MaterializationError,
    MaterializationPlan,
    MaterializedResource,
    ResourceMaterializer,
    VisibilityAwareMaterializer,
    docker_resource_mounts,
)
from securebench.workspaces.path_policy import (
    PathPolicy,
    PathPolicyDecision,
    PathPolicyError,
    validate_materialization_plan,
    validate_path_for_component,
    validate_workspace_mount_for_component,
)

__all__ = [
    "MaterializationError",
    "MaterializationPlan",
    "MaterializedResource",
    "PathPolicy",
    "PathPolicyDecision",
    "PathPolicyError",
    "ResourceMaterializer",
    "VisibilityAwareMaterializer",
    "docker_resource_mounts",
    "validate_materialization_plan",
    "validate_path_for_component",
    "validate_workspace_mount_for_component",
]
