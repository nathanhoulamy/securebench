"""Linux-only disk quota workspaces for filesystem-overlay candidates."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from securebench.errors import ConfigError
from securebench.path_safety import portable_paths_overlap
from securebench.sandboxes import DockerVolumeMount
from securebench.schemas.benchmark import (
    FILESYSTEM_OVERLAY_PROTECTED_PATHS,
    MAX_FILESYSTEM_OVERLAY_PATH_BYTES,
    MAX_FILESYSTEM_OVERLAY_PATH_DEPTH,
    MAX_FILESYSTEM_OVERLAY_ROOTS,
)
from securebench.tester_config import (
    MAX_OVERLAY_WORKSPACE_BYTES,
    MIN_OVERLAY_WORKSPACE_BYTES,
    OVERLAY_WORKSPACE_BLOCK_BYTES,
)


OVERLAY_WORKSPACE_FORMAT = "securebench.overlay-workspace/ext4-v1"
OVERLAY_WORKSPACE_LABEL = "securebench.overlay-workspace"
OVERLAY_WORKSPACE_LABEL_VALUE = "true"
OVERLAY_WORKSPACE_FORMAT_LABEL = "securebench.overlay-workspace.format"
SUPPORTED_DOCKER_STORAGE_DRIVERS = frozenset({"overlay2"})
OVERLAY_OPERATION_TIMEOUT_SECONDS = 30.0
OVERLAY_PROBE_TIMEOUT_SECONDS = 180.0
OVERLAY_PROBE_IMAGE = (
    "python:3.11-slim@sha256:"
    "9c900dea9e8fb7e16277c179b555cc72d29a352dbc33cff48ad5a0412fd5bfc7"
)
_LOOP_DEVICE_RE = re.compile(r"/dev/loop[0-9]+")


class OverlayWorkspaceUnavailable(ConfigError):
    """The production host cannot enforce the reviewed overlay quota boundary."""


class OverlayWorkspaceError(RuntimeError):
    """An overlay quota workspace could not be created, used, or removed safely."""


@dataclass(frozen=True)
class OverlayWorkspaceCapabilities:
    """Reviewed host facts established before any overlay Agent may start."""

    operating_system: str
    docker_operating_system: str
    docker_storage_driver: str


def require_overlay_workspace_host() -> OverlayWorkspaceCapabilities:
    """Fail closed unless this is the reviewed native-Linux Docker backend."""
    operating_system = platform.system()
    if operating_system != "Linux":
        raise OverlayWorkspaceUnavailable(
            "filesystem_overlay quota workspaces require a Linux production host"
        )
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise OverlayWorkspaceUnavailable(
            "filesystem_overlay quota workspaces require root for loop and mount operations"
        )
    for command in (
        "docker",
        "losetup",
        "mkfs.ext4",
        "mount",
        "mountpoint",
        "umount",
    ):
        if shutil.which(command) is None:
            raise OverlayWorkspaceUnavailable(
                f"filesystem_overlay quota workspaces require host command {command!r}"
            )

    try:
        completed = subprocess.run(
            ["docker", "info", "--format", "{{json .}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=OVERLAY_OPERATION_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OverlayWorkspaceUnavailable("could not query the Docker daemon") from exc
    if completed.returncode != 0:
        raise OverlayWorkspaceUnavailable("could not query the Docker daemon")
    try:
        info = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise OverlayWorkspaceUnavailable("Docker returned malformed capability data") from exc
    if not isinstance(info, dict):
        raise OverlayWorkspaceUnavailable("Docker returned malformed capability data")
    docker_os = info.get("OSType")
    storage_driver = info.get("Driver")
    if docker_os != "linux":
        raise OverlayWorkspaceUnavailable("filesystem_overlay requires a Linux Docker daemon")
    if storage_driver not in SUPPORTED_DOCKER_STORAGE_DRIVERS:
        supported = ", ".join(sorted(SUPPORTED_DOCKER_STORAGE_DRIVERS))
        raise OverlayWorkspaceUnavailable(
            "filesystem_overlay does not support Docker storage driver "
            f"{storage_driver!r}; expected one of: {supported}"
        )
    return OverlayWorkspaceCapabilities(
        operating_system=operating_system,
        docker_operating_system=docker_os,
        docker_storage_driver=storage_driver,
    )


class OverlayQuotaWorkspace:
    """One sparse ext4 filesystem and named Docker volume for one isolation unit."""

    def __init__(
        self,
        *,
        storage_root: Path,
        capacity_bytes: int,
        include_roots: tuple[str, ...],
        instance_id: str,
    ) -> None:
        self.storage_root = storage_root
        self.capacity_bytes = capacity_bytes
        self.include_roots = include_roots
        self.instance_id = instance_id
        self.instance_dir = storage_root / f"securebench-overlay-{instance_id}"
        self.backing_file = self.instance_dir / "workspace.ext4"
        self.mountpoint = self.instance_dir / "mounted"
        self.volume_name = f"securebench-overlay-{instance_id}"
        self.root_subpaths = tuple(
            f"roots/{index:04d}" for index in range(len(include_roots))
        )
        self.loop_device: str | None = None
        self._backing_created = False
        self._mounted = False
        self._volume_created = False

    @classmethod
    def create(
        cls,
        *,
        storage_root: str | Path,
        capacity_bytes: int,
        include_roots: tuple[str, ...],
        check_host: bool = True,
    ) -> "OverlayQuotaWorkspace":
        if check_host:
            require_overlay_workspace_host()
        capacity = _validate_capacity(capacity_bytes)
        roots = _validate_include_roots(include_roots)
        root = _validate_storage_root(storage_root)
        workspace = cls(
            storage_root=root,
            capacity_bytes=capacity,
            include_roots=roots,
            instance_id=uuid.uuid4().hex,
        )
        try:
            workspace._create()
        except BaseException as exc:
            try:
                workspace.close()
            except OverlayWorkspaceError as cleanup_exc:
                raise OverlayWorkspaceError(
                    "failed to create and roll back overlay quota workspace"
                ) from cleanup_exc
            if isinstance(exc, OverlayWorkspaceError):
                raise
            raise OverlayWorkspaceError("failed to create overlay quota workspace") from exc
        return workspace

    def docker_mounts(self, *, read_only: bool = False) -> tuple[DockerVolumeMount, ...]:
        """Map each declared root to its private subdirectory in the one volume."""
        if not self._volume_created:
            raise OverlayWorkspaceError("overlay quota workspace is not active")
        return tuple(
            DockerVolumeMount(
                source=self.volume_name,
                target=root,
                subpath=subpath,
                read_only=read_only,
            )
            for root, subpath in zip(self.include_roots, self.root_subpaths, strict=True)
        )

    def close(self) -> None:
        """Remove the volume before unmounting, detaching, and deleting its backing file."""
        if self._volume_created:
            completed = _run(
                ["docker", "volume", "rm", "--force", "--", self.volume_name],
                action="remove overlay Docker volume",
            )
            if completed.returncode != 0 and "no such volume" not in completed.stderr.lower():
                raise OverlayWorkspaceError("failed to remove overlay Docker volume")
            self._volume_created = False

        if self._mounted:
            completed = _run(
                ["umount", "--", str(self.mountpoint)],
                action="unmount overlay workspace",
            )
            if completed.returncode != 0:
                raise OverlayWorkspaceError("failed to unmount overlay workspace")
            self._mounted = False

        if self.loop_device is not None:
            completed = _run(
                ["losetup", "--detach", self.loop_device],
                action="detach overlay loop device",
            )
            if completed.returncode != 0:
                raise OverlayWorkspaceError("failed to detach overlay loop device")
            self.loop_device = None

        if self._backing_created:
            try:
                self.backing_file.unlink(missing_ok=True)
            except OSError as exc:
                raise OverlayWorkspaceError("failed to remove overlay backing file") from exc
            self._backing_created = False

        if self.instance_dir.exists():
            try:
                shutil.rmtree(self.instance_dir)
            except OSError as exc:
                raise OverlayWorkspaceError("failed to remove overlay workspace directory") from exc

    def __enter__(self) -> "OverlayQuotaWorkspace":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _create(self) -> None:
        try:
            self.instance_dir.mkdir(mode=0o700)
            self.mountpoint.mkdir(mode=0o700)
        except OSError as exc:
            raise OverlayWorkspaceError("failed to create overlay workspace directory") from exc
        descriptor: int | None = None
        try:
            descriptor = os.open(
                self.backing_file,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                0o600,
            )
            self._backing_created = True
            os.ftruncate(descriptor, self.capacity_bytes)
        except OSError as exc:
            raise OverlayWorkspaceError("failed to create sparse overlay backing file") from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
        stat = self.backing_file.stat()
        if stat.st_size != self.capacity_bytes or stat.st_blocks * 512 >= stat.st_size:
            raise OverlayWorkspaceError("overlay backing file is not sparse at the requested size")

        try:
            completed = _run(
                [
                    "losetup",
                    "--find",
                    "--show",
                    "--nooverlap",
                    str(self.backing_file),
                ],
                action="allocate overlay loop device",
            )
        except OverlayWorkspaceError:
            self.loop_device = _associated_loop_device(self.backing_file)
            raise
        loop_device = completed.stdout.strip()
        if _LOOP_DEVICE_RE.fullmatch(loop_device) is not None:
            self.loop_device = loop_device
        if completed.returncode != 0 or self.loop_device is None:
            raise OverlayWorkspaceError("failed to allocate overlay loop device")

        completed = _run(
            [
                "mkfs.ext4",
                "-q",
                "-F",
                "-m",
                "0",
                "-E",
                "lazy_itable_init=0,lazy_journal_init=0",
                self.loop_device,
            ],
            action="format overlay ext4 workspace",
        )
        if completed.returncode != 0:
            raise OverlayWorkspaceError("failed to format overlay ext4 workspace")

        try:
            completed = _run(
                [
                    "mount",
                    "-t",
                    "ext4",
                    "-o",
                    "nodev,nosuid",
                    self.loop_device,
                    str(self.mountpoint),
                ],
                action="mount overlay ext4 workspace",
            )
        except OverlayWorkspaceError:
            self._mounted = _mountpoint_is_active(self.mountpoint)
            raise
        if completed.returncode != 0:
            self._mounted = _mountpoint_is_active(self.mountpoint)
            raise OverlayWorkspaceError("failed to mount overlay ext4 workspace")
        self._mounted = True

        roots_dir = self.mountpoint / "roots"
        try:
            roots_dir.mkdir(mode=0o755)
            for subpath in self.root_subpaths:
                (self.mountpoint / subpath).mkdir(mode=0o755)
        except OSError as exc:
            raise OverlayWorkspaceError("failed to prepare overlay root subdirectories") from exc

        # The unique name is ours even if Docker returns an ambiguous failure;
        # mark it first so rollback always attempts removal.
        self._volume_created = True
        completed = _run(
            [
                "docker",
                "volume",
                "create",
                "--driver",
                "local",
                "--label",
                f"{OVERLAY_WORKSPACE_LABEL}={OVERLAY_WORKSPACE_LABEL_VALUE}",
                "--label",
                f"{OVERLAY_WORKSPACE_FORMAT_LABEL}={OVERLAY_WORKSPACE_FORMAT}",
                "--opt",
                "type=none",
                "--opt",
                "o=bind",
                "--opt",
                f"device={self.mountpoint}",
                self.volume_name,
            ],
            action="create overlay Docker volume",
        )
        if completed.returncode != 0 or completed.stdout.strip() != self.volume_name:
            raise OverlayWorkspaceError("failed to create overlay Docker volume")


def probe_overlay_workspace_backend(
    *,
    storage_root: str | Path,
    image: str = OVERLAY_PROBE_IMAGE,
) -> OverlayWorkspaceCapabilities:
    """Prove volume-subpath mounting, enforced ENOSPC, and complete cleanup."""
    capabilities = require_overlay_workspace_host()
    if re.search(r"(?:@sha256:|^sha256:)[0-9a-f]{64}$", image) is None:
        raise OverlayWorkspaceUnavailable("overlay probe image must be digest-pinned")
    try:
        inspected_image = _run(
            ["docker", "image", "inspect", image],
            action="inspect overlay probe image",
        )
    except OverlayWorkspaceError as exc:
        raise OverlayWorkspaceUnavailable(
            "could not inspect the digest-pinned overlay probe image"
        ) from exc
    if inspected_image.returncode != 0:
        raise OverlayWorkspaceUnavailable(
            "the digest-pinned overlay probe image must already be available locally"
        )
    try:
        cleanup_stale_overlay_workspaces(storage_root)
    except OverlayWorkspaceError as exc:
        raise OverlayWorkspaceUnavailable(
            "failed to recover stale overlay quota workspaces"
        ) from exc

    workspace: OverlayQuotaWorkspace | None = None
    loop_device: str | None = None
    probe_container = f"securebench-overlay-probe-{uuid.uuid4().hex}"
    try:
        workspace = OverlayQuotaWorkspace.create(
            storage_root=storage_root,
            capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
            include_roots=("/securebench-overlay-probe",),
            check_host=False,
        )
        loop_device = workspace.loop_device
        mount = workspace.docker_mounts()[0]
        mount_option = (
            f"type=volume,source={mount.source},target={mount.target},"
            f"volume-subpath={mount.subpath}"
        )
        probe_script = (
            "import errno,sys; p='/securebench-overlay-probe/fill'; "
            "f=open(p,'wb',buffering=0); b=b'x'*(1024*1024); code=4; "
            "\ntry:\n"
            "  for _ in range(96): f.write(b)\n"
            "except OSError as e:\n"
            "  code=0 if e.errno == errno.ENOSPC else 3\n"
            "finally:\n"
            "  f.close()\n"
            "sys.exit(code)"
        )
        completed = _run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                probe_container,
                "--entrypoint",
                "",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--memory",
                "128m",
                "--pids-limit",
                "32",
                "--mount",
                mount_option,
                image,
                "python",
                "-c",
                probe_script,
            ],
            action="probe enforced overlay out-of-space behavior",
            timeout=OVERLAY_PROBE_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise OverlayWorkspaceUnavailable(
                "overlay workspace did not produce an enforced ENOSPC result"
            )
    except OverlayWorkspaceUnavailable:
        raise
    except OverlayWorkspaceError as exc:
        raise OverlayWorkspaceUnavailable("overlay workspace backend probe failed") from exc
    finally:
        try:
            try:
                _remove_probe_container(probe_container)
            finally:
                if workspace is not None:
                    workspace.close()
        except OverlayWorkspaceUnavailable:
            raise
        except OverlayWorkspaceError as exc:
            raise OverlayWorkspaceUnavailable(
                "overlay workspace backend cleanup probe failed"
            ) from exc

    assert workspace is not None
    try:
        if workspace.instance_dir.exists() or workspace.backing_file.exists():
            raise OverlayWorkspaceUnavailable(
                "overlay workspace cleanup probe left host files"
            )
        completed = _run(
            ["docker", "container", "inspect", probe_container],
            action="inspect overlay probe container cleanup",
        )
        if completed.returncode == 0:
            raise OverlayWorkspaceUnavailable(
                "overlay workspace cleanup probe left a Docker container"
            )
        if "no such object" not in completed.stderr.lower():
            raise OverlayWorkspaceUnavailable(
                "could not prove overlay probe container cleanup"
            )
        if _docker_volume_exists(workspace.volume_name):
            raise OverlayWorkspaceUnavailable(
                "overlay workspace cleanup probe left a Docker volume"
            )
        if loop_device is not None:
            completed = _run(
                ["losetup", loop_device],
                action="inspect overlay loop cleanup",
            )
            if completed.returncode == 0:
                raise OverlayWorkspaceUnavailable(
                    "overlay workspace cleanup probe left a loop device"
                )
    except OverlayWorkspaceUnavailable:
        raise
    except OverlayWorkspaceError as exc:
        raise OverlayWorkspaceUnavailable(
            "could not prove complete overlay workspace cleanup"
        ) from exc
    return capabilities


def cleanup_stale_overlay_workspaces(storage_root: str | Path) -> None:
    """Recover quota resources left by a previously interrupted process."""
    try:
        root = _validate_storage_root(storage_root)
    except OverlayWorkspaceError as exc:
        raise OverlayWorkspaceUnavailable(
            "could not prepare stale overlay cleanup"
        ) from exc
    for instance_dir in sorted(root.iterdir()):
        match = re.fullmatch(r"securebench-overlay-([0-9a-f]{32})", instance_dir.name)
        if match is None:
            continue
        if instance_dir.is_symlink() or not instance_dir.is_dir():
            raise OverlayWorkspaceUnavailable("stale overlay workspace path is unsafe")
        instance_id = match.group(1)
        workspace = OverlayQuotaWorkspace(
            storage_root=root,
            capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
            include_roots=(),
            instance_id=instance_id,
        )
        workspace._backing_created = workspace.backing_file.is_file()
        workspace.loop_device = _associated_loop_device(workspace.backing_file)
        workspace._mounted = _mountpoint_is_active(workspace.mountpoint)
        workspace._volume_created = _docker_volume_exists(workspace.volume_name)
        try:
            workspace.close()
        except OverlayWorkspaceError as exc:
            raise OverlayWorkspaceUnavailable(
                "failed to clean a stale overlay quota workspace"
            ) from exc


def _remove_probe_container(name: str) -> None:
    completed = _run(
        ["docker", "rm", "-f", name],
        action="remove overlay probe container",
    )
    if completed.returncode != 0 and "no such container" not in completed.stderr.lower():
        raise OverlayWorkspaceUnavailable("failed to remove overlay probe container")


def _docker_volume_exists(name: str) -> bool:
    completed = _run(
        ["docker", "volume", "inspect", name],
        action="inspect overlay Docker volume",
    )
    if completed.returncode == 0:
        return True
    if "no such volume" in completed.stderr.lower():
        return False
    raise OverlayWorkspaceError("could not establish overlay Docker volume state")


def _associated_loop_device(backing_file: Path) -> str | None:
    if not backing_file.exists():
        return None
    completed = _run(
        [
            "losetup",
            "--associated",
            str(backing_file),
            "--noheadings",
            "--output",
            "NAME",
        ],
        action="inspect overlay loop device",
    )
    if completed.returncode != 0:
        raise OverlayWorkspaceError("failed to inspect overlay loop device")
    devices = tuple(line.strip() for line in completed.stdout.splitlines() if line.strip())
    if not devices:
        return None
    if len(devices) != 1 or _LOOP_DEVICE_RE.fullmatch(devices[0]) is None:
        raise OverlayWorkspaceError("overlay backing file has ambiguous loop devices")
    return devices[0]


def _mountpoint_is_active(path: Path) -> bool:
    completed = _run(
        ["mountpoint", "--quiet", "--", str(path)],
        action="inspect overlay mountpoint",
    )
    if completed.returncode not in (0, 1):
        raise OverlayWorkspaceError("failed to inspect overlay mountpoint")
    return completed.returncode == 0


def _validate_capacity(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OverlayWorkspaceError("overlay workspace capacity must be an integer")
    if not MIN_OVERLAY_WORKSPACE_BYTES <= value <= MAX_OVERLAY_WORKSPACE_BYTES:
        raise OverlayWorkspaceError("overlay workspace capacity is outside framework bounds")
    if value % OVERLAY_WORKSPACE_BLOCK_BYTES:
        raise OverlayWorkspaceError(
            f"overlay workspace capacity must align to {OVERLAY_WORKSPACE_BLOCK_BYTES} bytes"
        )
    return value


def _validate_include_roots(values: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not values:
        raise OverlayWorkspaceError("overlay workspace requires include roots")
    if len(values) > MAX_FILESYSTEM_OVERLAY_ROOTS:
        raise OverlayWorkspaceError("overlay workspace has too many include roots")
    roots: list[PurePosixPath] = []
    for value in values:
        if not isinstance(value, str):
            raise OverlayWorkspaceError("overlay include root must be text")
        path = PurePosixPath(value)
        if (
            value.startswith("//")
            or not path.is_absolute()
            or str(path) == "/"
            or str(path) != value
            or ".." in path.parts
            or "\\" in value
            or "\x00" in value
        ):
            raise OverlayWorkspaceError("overlay include root must be canonical and absolute")
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise OverlayWorkspaceError("overlay include root is not valid UTF-8") from exc
        if (
            len(encoded) > MAX_FILESYSTEM_OVERLAY_PATH_BYTES
            or len(path.parts[1:]) > MAX_FILESYSTEM_OVERLAY_PATH_DEPTH
        ):
            raise OverlayWorkspaceError("overlay include root exceeds path bounds")
        if any(
            portable_paths_overlap(path, protected)
            for protected in FILESYSTEM_OVERLAY_PROTECTED_PATHS
        ):
            raise OverlayWorkspaceError("overlay include root overlaps a protected path")
        if any(portable_paths_overlap(path, existing) for existing in roots):
            raise OverlayWorkspaceError("overlay include roots may not overlap")
        roots.append(path)
    return tuple(str(root) for root in roots)


def _validate_storage_root(value: str | Path) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise OverlayWorkspaceError("overlay storage root must be absolute")
    if root.is_symlink():
        raise OverlayWorkspaceError("overlay storage root must not be a symlink")
    try:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise OverlayWorkspaceError("could not prepare overlay storage root") from exc
    if resolved == Path(resolved.anchor) or not resolved.is_dir():
        raise OverlayWorkspaceError("overlay storage root is unsafe")
    return resolved


def _run(
    command: list[str],
    *,
    action: str,
    timeout: float = OVERLAY_OPERATION_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OverlayWorkspaceError(f"failed to {action}") from exc
