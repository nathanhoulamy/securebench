"""Workspace materialization and path-policy helpers."""

from securebench.workspaces.materialization import (
    MaterializationError,
    MaterializationPlan,
    MaterializedResource,
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
from securebench.workspaces.overlay_quota import (
    OverlayQuotaWorkspace,
    OverlayWorkspaceCapabilities,
    OverlayWorkspaceError,
    OverlayWorkspaceUnavailable,
    cleanup_stale_overlay_workspaces,
    probe_overlay_workspace_backend,
    require_overlay_workspace_host,
)

__all__ = [
    "MaterializationError",
    "MaterializationPlan",
    "MaterializedResource",
    "OverlayQuotaWorkspace",
    "OverlayWorkspaceCapabilities",
    "OverlayWorkspaceError",
    "OverlayWorkspaceUnavailable",
    "PathPolicy",
    "PathPolicyDecision",
    "PathPolicyError",
    "VisibilityAwareMaterializer",
    "docker_resource_mounts",
    "cleanup_stale_overlay_workspaces",
    "probe_overlay_workspace_backend",
    "require_overlay_workspace_host",
    "validate_materialization_plan",
    "validate_path_for_component",
    "validate_workspace_mount_for_component",
]
