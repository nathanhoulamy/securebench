"""Linux-only Agent staging and stopped-state filesystem-overlay capture."""

from __future__ import annotations

import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from securebench.candidates.extraction import (
    CandidateProductionError,
    CandidateProductionTimeout,
)
from securebench.candidates.models import CandidateCaptureError, StoredCandidate
from securebench.candidates.overlay import (
    OverlayScanLimits,
    OverlayReservedMount,
    ScannedOverlayRoot,
    MAX_OVERLAY_CHANGED_BYTES,
    MAX_OVERLAY_CHANGED_PATHS,
    capture_filesystem_overlay_from_baseline,
    scan_overlay_roots,
)
from securebench.candidates.store import CandidateStore
from securebench.path_safety import portable_path_is_relative_to, portable_paths_overlap
from securebench.sandboxes import (
    CommandResult,
    DockerBindMount,
    DockerSandbox,
    DockerSandboxError,
)
from securebench.sandboxes.base import BoundedProcessResult, run_bounded_subprocess
from securebench.schemas.benchmark import FilesystemOverlayCandidate
from securebench.workspaces.overlay_quota import (
    OVERLAY_OPERATION_TIMEOUT_SECONDS,
    OverlayQuotaWorkspace,
    OverlayWorkspaceError,
)


OVERLAY_AGENT_INPUTS_TARGET = "/opt/securebench/agent-inputs"
OVERLAY_AGENT_TMPFS = (
    "/tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777",
)
OVERLAY_BASELINE_TIMEOUT_SECONDS = 120.0
_PINNED_IMAGE_RE = re.compile(r"(?:.+@sha256:|^sha256:)[0-9a-f]{64}")


class OverlayAgentInfrastructureError(RuntimeError):
    """Trusted overlay staging or Agent isolation failed."""


@dataclass(frozen=True)
class OverlayAgentCaptureResult:
    candidate: StoredCandidate
    agent_result: CommandResult


def materialize_overlay_image_roots(
    image: str,
    workspace: OverlayQuotaWorkspace,
    *,
    scan_limits: OverlayScanLimits = OverlayScanLimits(),
) -> dict[str, ScannedOverlayRoot]:
    """Copy declared roots from one pinned image into the bounded quota volume."""
    _validate_pinned_image(image)
    roots = workspace.host_roots()
    for destination in roots.values():
        try:
            with os.scandir(destination) as entries:
                if next(entries, None) is not None:
                    raise OverlayAgentInfrastructureError(
                        "overlay baseline destination is not empty"
                    )
        except OSError as exc:
            raise OverlayAgentInfrastructureError(
                "overlay baseline destination cannot be inspected"
            ) from exc

    container = f"securebench-overlay-baseline-{uuid.uuid4().hex}"
    deadline = time.monotonic() + OVERLAY_BASELINE_TIMEOUT_SECONDS
    try:
        created = _run_materializer(
            ["docker", "create", "--name", container, image],
            timeout=_remaining(deadline),
        )
        if created.returncode != 0:
            raise OverlayAgentInfrastructureError(
                "failed to create the pinned-image baseline container"
            )
        for root, destination in roots.items():
            copied = _run_materializer(
                ["docker", "cp", "--archive", f"{container}:{root}/.", str(destination)],
                timeout=_remaining(deadline),
            )
            if copied.returncode != 0:
                raise OverlayAgentInfrastructureError(
                    f"pinned image does not expose a materializable directory at {root!r}"
                )
    finally:
        removed = _run_materializer(
            ["docker", "rm", "-f", container],
            timeout=OVERLAY_OPERATION_TIMEOUT_SECONDS,
        )
        if removed.returncode != 0 and "no such container" not in removed.stderr.lower():
            raise OverlayAgentInfrastructureError(
                "failed to remove the baseline materialization container"
            )

    try:
        return scan_overlay_roots(
            workspace.include_roots,
            roots,
            limits=scan_limits,
            label="baseline",
        )
    except CandidateCaptureError as exc:
        raise OverlayAgentInfrastructureError(
            "pinned-image overlay baseline violates the reviewed filesystem contract"
        ) from exc


def run_filesystem_overlay_agent_capture(
    *,
    image: str,
    command: str | list[str] | tuple[str, ...],
    workdir: str,
    spec: FilesystemOverlayCandidate,
    store: CandidateStore,
    baseline_digest: str,
    storage_root: str | Path,
    capacity_bytes: int,
    trusted_inputs_root: str | Path,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
    env_names: tuple[str, ...] = (),
    network: str = "none",
    public_mounts: tuple[DockerBindMount, ...] = (),
    preflight_command: str | list[str] | tuple[str, ...] | None = None,
    scan_limits: OverlayScanLimits = OverlayScanLimits(),
    _workspace_factory: Callable[..., OverlayQuotaWorkspace] = OverlayQuotaWorkspace.create,
    _sandbox_factory: Callable[..., DockerSandbox] = DockerSandbox,
    _materializer: Callable[..., dict[str, ScannedOverlayRoot]] = materialize_overlay_image_roots,
) -> OverlayAgentCaptureResult:
    """Run one Agent, remove it, capture one Candidate, and destroy Agent state."""
    _validate_pinned_image(image)
    _validate_agent_contract(spec, workdir, baseline_digest)
    trusted_inputs = _validate_trusted_inputs_root(trusted_inputs_root)
    _validate_agent_mount_plan(spec.include_roots, public_mounts)
    workspace: OverlayQuotaWorkspace | None = None
    try:
        workspace = _workspace_factory(
            storage_root=storage_root,
            capacity_bytes=capacity_bytes,
            include_roots=spec.include_roots,
        )
        if workspace.include_roots != spec.include_roots:
            raise OverlayAgentInfrastructureError(
                "overlay quota workspace roots do not match the Candidate contract"
            )
        baseline = _materializer(image, workspace, scan_limits=scan_limits)
        reserved_mounts = _reserved_overlay_mounts(
            baseline,
            spec.include_roots,
            public_mounts,
        )
        sandbox = _sandbox_factory(
            image=image,
            root=trusted_inputs,
            env_names=env_names,
            env=env,
            persistent=True,
            network=network,
            cap_add=("DAC_OVERRIDE",),
            read_only=True,
            tmpfs=OVERLAY_AGENT_TMPFS,
            mounts=public_mounts,
            volume_mounts=workspace.docker_mounts(read_only=False),
            workspace_mount_target=OVERLAY_AGENT_INPUTS_TARGET,
            workspace_read_only=True,
            allow_resource_overrides=False,
        )
        try:
            if preflight_command is not None:
                preflight = sandbox.run(
                    preflight_command,
                    workdir=workdir,
                    timeout=timeout,
                )
                if preflight.timed_out:
                    raise OverlayAgentInfrastructureError(
                        "overlay Agent harness preflight timed out"
                    )
                if preflight.exit_code != 0:
                    raise OverlayAgentInfrastructureError(
                        "overlay Agent harness preflight failed"
                    )
            result = sandbox.run(command, workdir=workdir, timeout=timeout)
        finally:
            try:
                sandbox.close()
            except Exception as exc:
                raise OverlayAgentInfrastructureError(
                    "failed to remove the Agent container before overlay capture"
                ) from exc
        if result.timed_out:
            raise CandidateProductionTimeout(result)
        if result.exit_code != 0:
            raise CandidateProductionError(
                f"Agent failed before filesystem_overlay capture (exit code {result.exit_code})"
            )
        candidate = capture_filesystem_overlay_from_baseline(
            baseline,
            workspace.host_roots(),
            spec,
            store,
            baseline_digest=baseline_digest,
            scan_limits=scan_limits,
            reserved_mounts=reserved_mounts,
        )
        return OverlayAgentCaptureResult(candidate=candidate, agent_result=result)
    except (CandidateCaptureError, CandidateProductionError, CandidateProductionTimeout):
        raise
    except (DockerSandboxError, OverlayWorkspaceError, ValueError) as exc:
        raise OverlayAgentInfrastructureError("overlay Agent infrastructure failed") from exc
    finally:
        if workspace is not None:
            try:
                workspace.close()
            except OverlayWorkspaceError as exc:
                raise OverlayAgentInfrastructureError(
                    "failed to destroy the Agent overlay workspace"
                ) from exc


def _validate_pinned_image(image: str) -> None:
    if not isinstance(image, str) or _PINNED_IMAGE_RE.fullmatch(image) is None:
        raise OverlayAgentInfrastructureError(
            "filesystem_overlay Agent image must be digest-pinned"
        )


def _validate_agent_contract(
    spec: FilesystemOverlayCandidate,
    workdir: str,
    baseline_digest: str,
) -> None:
    if not isinstance(spec, FilesystemOverlayCandidate):
        raise OverlayAgentInfrastructureError(
            "overlay Agent capture requires a filesystem_overlay Candidate contract"
        )
    if (
        spec.max_changed_paths > MAX_OVERLAY_CHANGED_PATHS
        or spec.max_changed_bytes > MAX_OVERLAY_CHANGED_BYTES
    ):
        raise OverlayAgentInfrastructureError(
            "filesystem_overlay Candidate bounds exceed framework capacity"
        )
    if (
        not isinstance(baseline_digest, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", baseline_digest) is None
    ):
        raise OverlayAgentInfrastructureError("overlay baseline digest is invalid")
    if not isinstance(workdir, str):
        raise OverlayAgentInfrastructureError("overlay Agent workdir is invalid")
    path = PurePosixPath(workdir)
    if (
        not path.is_absolute()
        or str(path) != workdir
        or workdir.startswith("//")
        or ".." in path.parts
        or "\\" in workdir
        or "\x00" in workdir
        or not any(path.is_relative_to(PurePosixPath(root)) for root in spec.include_roots)
    ):
        raise OverlayAgentInfrastructureError(
            "overlay Agent workdir must be contained by an include root"
        )


def _validate_trusted_inputs_root(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise OverlayAgentInfrastructureError(
            "overlay Agent trusted-input root must be an absolute real directory"
        )
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise OverlayAgentInfrastructureError(
            "overlay Agent trusted-input root is inaccessible"
        ) from exc
    if resolved == Path(resolved.anchor) or not resolved.is_dir():
        raise OverlayAgentInfrastructureError("overlay Agent trusted-input root is unsafe")
    if ":" in os.fspath(resolved):
        raise OverlayAgentInfrastructureError(
            "overlay Agent trusted-input root is not safe for a Docker bind mount"
        )
    return resolved


def _validate_agent_mount_plan(
    include_roots: tuple[str, ...],
    public_mounts: tuple[DockerBindMount, ...],
) -> None:
    input_target = PurePosixPath(OVERLAY_AGENT_INPUTS_TARGET)
    roots = tuple(PurePosixPath(root) for root in include_roots)
    if any(portable_paths_overlap(input_target, root) for root in roots):
        raise OverlayAgentInfrastructureError(
            "overlay roots overlap framework-owned Agent inputs"
        )
    for mount in public_mounts:
        if (
            not isinstance(mount, DockerBindMount)
            or not isinstance(mount.target, str)
            or not mount.read_only
        ):
            raise OverlayAgentInfrastructureError(
                "overlay Agent public mounts must be explicit read-only bind mounts"
            )
        target = PurePosixPath(mount.target)
        if (
            not target.is_absolute()
            or mount.target.startswith("//")
            or str(target) != mount.target
            or ".." in target.parts
            or "\\" in mount.target
            or "\x00" in mount.target
        ):
            raise OverlayAgentInfrastructureError(
                "overlay Agent public mount targets must be canonical absolute paths"
            )
        for root in roots:
            if portable_path_is_relative_to(root, target):
                raise OverlayAgentInfrastructureError(
                    "a public mount may not replace or contain an overlay root"
                )
        if portable_paths_overlap(target, input_target):
            raise OverlayAgentInfrastructureError(
                "public mounts may not overlap framework-owned Agent inputs"
            )


def _reserved_overlay_mounts(
    baseline: dict[str, ScannedOverlayRoot],
    include_roots: tuple[str, ...],
    public_mounts: tuple[DockerBindMount, ...],
) -> tuple[OverlayReservedMount, ...]:
    """Validate and record public mount targets nested below captured roots."""
    reservations: list[OverlayReservedMount] = []
    for mount in public_mounts:
        target = PurePosixPath(mount.target)
        matching_roots = tuple(
            root
            for root in include_roots
            if target.is_relative_to(PurePosixPath(root))
        )
        if not matching_roots:
            continue
        if len(matching_roots) != 1:
            raise OverlayAgentInfrastructureError(
                "overlay public mount selects an ambiguous include root"
            )
        root = matching_roots[0]
        relative = target.relative_to(PurePosixPath(root))
        if not relative.parts:
            raise OverlayAgentInfrastructureError(
                "a public mount may not replace an overlay root"
            )
        source = Path(mount.source)
        if source.is_symlink():
            raise OverlayAgentInfrastructureError(
                "overlay public mount source must not be a symlink"
            )
        if source.is_file():
            kind = "regular_file"
        elif source.is_dir():
            kind = "directory"
        else:
            raise OverlayAgentInfrastructureError(
                "overlay public mount source must be an existing file or directory"
            )
        scanned = baseline.get(root)
        if scanned is None:
            raise OverlayAgentInfrastructureError(
                "overlay public mount root is absent from the trusted baseline"
            )
        nodes = {node.path: node for node in scanned.nodes}
        relative_text = relative.as_posix()
        node = nodes.get(relative_text)
        if node is None or node.kind != kind:
            raise OverlayAgentInfrastructureError(
                "overlay public mount target must already exist with the matching type "
                "in the trusted baseline"
            )
        for depth in range(1, len(relative.parts)):
            parent = PurePosixPath(*relative.parts[:depth]).as_posix()
            parent_node = nodes.get(parent)
            if parent_node is None or parent_node.kind != "directory":
                raise OverlayAgentInfrastructureError(
                    "overlay public mount parents must be real baseline directories"
                )
        reservations.append(
            OverlayReservedMount(root=root, path=relative_text, kind=kind)
        )
    return tuple(reservations)


def _run_materializer(
    command: list[str],
    *,
    timeout: float,
) -> BoundedProcessResult:
    try:
        return run_bounded_subprocess(command, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise OverlayAgentInfrastructureError(
            "overlay baseline materialization command failed"
        ) from exc


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise OverlayAgentInfrastructureError(
            "overlay baseline materialization exceeded its time bound"
        )
    return remaining
