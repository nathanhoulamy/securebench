"""Internal path policy validation for materialized resources and mounts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from securebench.resources import Component


MANDATORY_DENIED_PATHS = (
    "/ground_truth",
    "/scorer",
    "/eval",
    "/task/hidden.json",
    "/task/evaluation_inputs.json",
    "/input/hidden.json",
    "/output/score.json",
)

COMPONENT_ALLOWED_ROOTS: dict[str, tuple[str, ...]] = {
    "agent": ("securebench/public",),
    "test_sandbox": ("securebench/public", "securebench/evaluation_inputs"),
    "evaluator": ("securebench/evaluator",),
}

WORKSPACE_MOUNT_RESERVED_ROOTS: dict[str, tuple[str, ...]] = {
    "agent": ("securebench/evaluation_inputs", "securebench/evaluator"),
    "test_sandbox": ("securebench/evaluation_inputs", "securebench/evaluator"),
    "evaluator": (),
}


class PathPolicyError(ValueError):
    """Raised when a materialized path is unsafe or unauthorized."""


@dataclass(frozen=True)
class PathPolicyDecision:
    """Decision returned by a path policy check."""

    component: str
    path: str
    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class PathPolicy:
    """Validate materialized paths for one component."""

    component: str
    allowed_roots: tuple[str, ...]
    denied_paths: tuple[str, ...] = MANDATORY_DENIED_PATHS

    @classmethod
    def for_component(cls, component: Component) -> "PathPolicy":
        if component == "result":
            raise PathPolicyError("result is not a path-policy target")
        roots = COMPONENT_ALLOWED_ROOTS.get(component)
        if roots is None:
            raise PathPolicyError(f"unsupported path-policy component: {component!r}")
        return cls(component=component, allowed_roots=roots)

    def check(self, path: str | PurePosixPath) -> PathPolicyDecision:
        try:
            candidate = _safe_relative_path(path)
        except PathPolicyError as exc:
            return PathPolicyDecision(self.component, str(path), False, str(exc))

        for denied in self.denied_paths:
            denied_path = _policy_path(denied)
            if _same_or_parent(denied_path, candidate):
                return PathPolicyDecision(
                    self.component,
                    str(candidate),
                    False,
                    f"path is denied by policy: {candidate}",
                )

        allowed_roots = tuple(_policy_path(root) for root in self.allowed_roots)
        if not any(_same_or_parent(root, candidate) for root in allowed_roots):
            roots = ", ".join(str(root) for root in allowed_roots)
            return PathPolicyDecision(
                self.component,
                str(candidate),
                False,
                f"path is outside allowed roots for {self.component}: {candidate} (allowed: {roots})",
            )

        return PathPolicyDecision(self.component, str(candidate), True)

    def validate(self, path: str | PurePosixPath) -> PathPolicyDecision:
        decision = self.check(path)
        if not decision.allowed:
            raise PathPolicyError(decision.reason)
        return decision


def validate_path_for_component(component: Component, path: str | PurePosixPath) -> PathPolicyDecision:
    """Validate one path against the default policy for a component."""
    return PathPolicy.for_component(component).validate(path)


def validate_workspace_mount_for_component(component: Component, path: str | PurePosixPath) -> PathPolicyDecision:
    """Validate a benchmark-defined workspace mount path for one component."""
    if component == "result":
        raise PathPolicyError("result is not a workspace-mount target")
    if component not in WORKSPACE_MOUNT_RESERVED_ROOTS:
        raise PathPolicyError(f"unsupported workspace-mount component: {component!r}")

    try:
        candidate = _safe_relative_path(path)
    except PathPolicyError as exc:
        raise PathPolicyError(str(exc)) from exc

    for denied in MANDATORY_DENIED_PATHS:
        denied_path = _policy_path(denied)
        if _same_or_parent(denied_path, candidate):
            raise PathPolicyError(f"path is denied by policy: {candidate}")

    for reserved in WORKSPACE_MOUNT_RESERVED_ROOTS[component]:
        reserved_path = _policy_path(reserved)
        if _same_or_parent(reserved_path, candidate):
            raise PathPolicyError(f"path is reserved for non-public materialization: {candidate}")

    return PathPolicyDecision(component, str(candidate), True)


def validate_materialization_plan(plan: object) -> None:
    """Validate all paths in a materialization plan and reject collisions."""
    component = getattr(plan, "component", None)
    policy = PathPolicy.for_component(component)
    seen: set[PurePosixPath] = set()

    for resource in getattr(plan, "resources", ()):
        resource_component = getattr(resource, "component", None)
        if resource_component != component:
            raise PathPolicyError(
                f"materialized resource component {resource_component!r} does not match plan component {component!r}"
            )
        path = getattr(resource, "relative_path", None)
        placement = getattr(resource, "placement", "internal")
        if placement == "internal":
            decision = policy.validate(path)
        elif placement == "workspace":
            decision = validate_workspace_mount_for_component(component, path)
        else:
            raise PathPolicyError(f"unsupported materialized resource placement: {placement!r}")
        candidate = _policy_path(decision.path)
        if any(_same_or_parent(existing, candidate) or _same_or_parent(candidate, existing) for existing in seen):
            raise PathPolicyError(f"duplicate materialized path: {decision.path}")
        seen.add(candidate)


def _safe_relative_path(path: str | PurePosixPath) -> PurePosixPath:
    if isinstance(path, PurePosixPath):
        raw = str(path)
    else:
        raw = path
    if not isinstance(raw, str) or not raw:
        raise PathPolicyError("path must be a non-empty relative path")
    if "\\" in raw:
        raise PathPolicyError(f"path may not contain backslashes: {raw!r}")

    candidate = PurePosixPath(raw)
    if candidate.is_absolute():
        raise PathPolicyError(f"path may not be absolute: {raw!r}")
    if ".." in candidate.parts:
        raise PathPolicyError(f"path may not contain '..': {raw!r}")
    if str(candidate) in ("", "."):
        raise PathPolicyError("path must be a non-empty relative path")
    return candidate


def _policy_path(path: str | PurePosixPath) -> PurePosixPath:
    raw = str(path)
    if raw.startswith("/"):
        raw = raw.lstrip("/")
    return _safe_relative_path(raw)


def _same_or_parent(parent: PurePosixPath, child: PurePosixPath) -> bool:
    return child == parent or child.is_relative_to(parent)
