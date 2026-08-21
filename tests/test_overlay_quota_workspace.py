from __future__ import annotations

import os
import platform
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from securebench.tester_config import MIN_OVERLAY_WORKSPACE_BYTES
from securebench.workspaces.overlay_quota import (
    OverlayQuotaWorkspace,
    OverlayWorkspaceCapabilities,
    OverlayWorkspaceError,
    OverlayWorkspaceUnavailable,
    cleanup_stale_overlay_workspaces,
    probe_overlay_workspace_backend,
    require_overlay_workspace_host,
)


def _completed(*, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class FakeOverlayCommands:
    def __init__(self):
        self.commands = []
        self.fail_prefix: tuple[str, ...] | None = None

    def __call__(self, command, *, action, timeout=30.0):
        self.commands.append((tuple(command), action, timeout))
        if self.fail_prefix is not None and tuple(command[: len(self.fail_prefix)]) == self.fail_prefix:
            return _completed(returncode=1, stderr="injected failure")
        if command[0] == "losetup" and "--show" in command:
            return _completed(stdout="/dev/loop7\n")
        if command[0] == "losetup" and "--associated" in command:
            return _completed(stdout="/dev/loop7\n")
        if command[:3] == ["docker", "volume", "create"]:
            return _completed(stdout=command[-1] + "\n")
        return _completed()


def _create(monkeypatch, tmp_path, commands, *, roots=("/app", "/etc/nginx")):
    monkeypatch.setattr("securebench.workspaces.overlay_quota._run", commands)
    return OverlayQuotaWorkspace.create(
        storage_root=tmp_path / "overlay-storage",
        capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
        include_roots=roots,
        check_host=False,
    )


def test_quota_workspace_uses_one_sparse_ext4_volume_with_root_subpaths(
    monkeypatch,
    tmp_path,
):
    commands = FakeOverlayCommands()
    workspace = _create(monkeypatch, tmp_path, commands)

    assert workspace.backing_file.stat().st_size == MIN_OVERLAY_WORKSPACE_BYTES
    assert workspace.backing_file.stat().st_blocks * 512 < MIN_OVERLAY_WORKSPACE_BYTES
    mounts = workspace.docker_mounts()
    assert [mount.source for mount in mounts] == [workspace.volume_name] * 2
    assert [mount.target for mount in mounts] == ["/app", "/etc/nginx"]
    assert [mount.subpath for mount in mounts] == ["roots/0000", "roots/0001"]
    assert all((workspace.mountpoint / mount.subpath).is_dir() for mount in mounts)

    workspace.close()

    command_names = [command[0][0] for command in commands.commands]
    assert command_names[:4] == ["losetup", "mkfs.ext4", "mount", "docker"]
    assert command_names[-3:] == ["docker", "umount", "losetup"]
    volume_create = commands.commands[3][0]
    assert "type=none" in volume_create
    assert "o=bind" in volume_create
    assert f"device={workspace.mountpoint}" in volume_create
    assert not workspace.instance_dir.exists()


def test_quota_workspace_rolls_back_partial_creation(monkeypatch, tmp_path):
    commands = FakeOverlayCommands()
    commands.fail_prefix = ("mkfs.ext4",)
    monkeypatch.setattr("securebench.workspaces.overlay_quota._run", commands)

    with pytest.raises(OverlayWorkspaceError, match="format"):
        OverlayQuotaWorkspace.create(
            storage_root=tmp_path / "overlay-storage",
            capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
            include_roots=("/app",),
            check_host=False,
        )

    assert any(command[:2] == ("losetup", "--detach") for command, _, _ in commands.commands)
    assert not list((tmp_path / "overlay-storage").glob("securebench-overlay-*"))


def test_quota_cleanup_stops_before_unmount_when_volume_removal_fails(
    monkeypatch,
    tmp_path,
):
    commands = FakeOverlayCommands()
    workspace = _create(monkeypatch, tmp_path, commands, roots=("/app",))
    commands.fail_prefix = ("docker", "volume", "rm")

    with pytest.raises(OverlayWorkspaceError, match="Docker volume"):
        workspace.close()

    assert workspace.backing_file.exists()
    assert workspace.loop_device == "/dev/loop7"
    assert workspace._mounted is True

    commands.fail_prefix = None
    workspace.close()
    assert not workspace.instance_dir.exists()


def test_preflight_recovers_a_stale_interrupted_workspace(monkeypatch, tmp_path):
    commands = FakeOverlayCommands()
    workspace = _create(monkeypatch, tmp_path, commands, roots=("/app",))

    cleanup_stale_overlay_workspaces(workspace.storage_root)

    assert not workspace.instance_dir.exists()
    assert any(
        command[:3] == ("docker", "volume", "inspect")
        for command, _, _ in commands.commands
    )
    assert any(command[:2] == ("umount", "--") for command, _, _ in commands.commands)
    assert any(
        command[:2] == ("losetup", "--detach")
        for command, _, _ in commands.commands
    )


@pytest.mark.parametrize("interruption", [RuntimeError("failure"), KeyboardInterrupt()])
def test_quota_workspace_cleans_after_failure_or_interruption(
    monkeypatch,
    tmp_path,
    interruption,
):
    commands = FakeOverlayCommands()
    workspace = _create(monkeypatch, tmp_path, commands, roots=("/app",))

    with pytest.raises(type(interruption)):
        with workspace:
            raise interruption

    assert not workspace.instance_dir.exists()


def test_quota_workspace_rejects_unaligned_capacity_and_unsafe_roots(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        "securebench.workspaces.overlay_quota.require_overlay_workspace_host",
        lambda: None,
    )
    with pytest.raises(OverlayWorkspaceError, match="align"):
        OverlayQuotaWorkspace.create(
            storage_root=tmp_path / "overlay-storage",
            capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES + 1,
            include_roots=("/app",),
        )
    with pytest.raises(OverlayWorkspaceError, match="may not overlap"):
        OverlayQuotaWorkspace.create(
            storage_root=tmp_path / "overlay-storage",
            capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
            include_roots=("/app", "/APP/results"),
        )
    with pytest.raises(OverlayWorkspaceError, match="protected path"):
        OverlayQuotaWorkspace.create(
            storage_root=tmp_path / "overlay-storage",
            capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
            include_roots=("/proc/agent",),
        )


def test_overlay_host_probe_rejects_non_linux_before_running_commands(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Darwin")

    with pytest.raises(OverlayWorkspaceUnavailable, match="Linux production host"):
        require_overlay_workspace_host()


def test_overlay_host_probe_rejects_unreviewed_docker_storage_driver(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    monkeypatch.setattr(shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout='{"OSType":"linux","Driver":"btrfs"}',
            stderr="",
        ),
    )

    with pytest.raises(OverlayWorkspaceUnavailable, match="storage driver"):
        require_overlay_workspace_host()


def test_backend_probe_checks_enospc_volume_subpaths_and_complete_cleanup(
    monkeypatch,
    tmp_path,
):
    commands = []
    volume_exists = False

    def fake_run(command, *, action, timeout=30.0):
        nonlocal volume_exists
        commands.append(tuple(command))
        if command[0] == "losetup" and "--show" in command:
            return _completed(stdout="/dev/loop7\n")
        if command[:3] == ["docker", "volume", "create"]:
            volume_exists = True
            return _completed(stdout=command[-1] + "\n")
        if command[:3] == ["docker", "volume", "rm"]:
            volume_exists = False
            return _completed()
        if command[:3] == ["docker", "volume", "inspect"]:
            if volume_exists:
                return _completed(stdout="[]")
            return _completed(returncode=1, stderr="No such volume")
        if command[:3] == ["docker", "container", "inspect"]:
            return _completed(returncode=1, stderr="No such object")
        if command[:3] == ["docker", "rm", "-f"]:
            return _completed(returncode=1, stderr="No such container")
        if command[0] == "losetup" and "--associated" in command:
            return _completed()
        if command[:2] == ["losetup", "/dev/loop7"]:
            return _completed(returncode=1, stderr="No such device")
        return _completed()

    capabilities = OverlayWorkspaceCapabilities("Linux", "linux", "overlay2")
    monkeypatch.setattr(
        "securebench.workspaces.overlay_quota.require_overlay_workspace_host",
        lambda: capabilities,
    )
    monkeypatch.setattr("securebench.workspaces.overlay_quota._run", fake_run)

    result = probe_overlay_workspace_backend(
        storage_root=tmp_path / "overlay-storage",
        image="sha256:" + "a" * 64,
    )

    assert result == capabilities
    docker_run = next(command for command in commands if command[:2] == ("docker", "run"))
    mount_option = docker_run[docker_run.index("--mount") + 1]
    assert "volume-subpath=roots/0000" in mount_option
    assert "--read-only" in docker_run
    assert volume_exists is False
    assert not list((tmp_path / "overlay-storage").glob("securebench-overlay-*"))


@pytest.mark.skipif(
    os.environ.get("SECUREBENCH_RUN_REAL_DOCKER_OVERLAY_TESTS") != "1",
    reason="requires an explicitly provisioned root Linux Docker host",
)
def test_real_docker_quota_and_cleanup_after_success_failure_and_interruption(tmp_path):
    if platform.system() != "Linux" or os.geteuid() != 0:
        pytest.skip("requires a root Linux host")
    image = os.environ.get("SECUREBENCH_OVERLAY_PROBE_IMAGE")
    if image is None:
        pytest.skip("SECUREBENCH_OVERLAY_PROBE_IMAGE must name a locally available pinned image")
    from securebench.workspaces.overlay_quota import probe_overlay_workspace_backend

    capabilities = probe_overlay_workspace_backend(
        storage_root=tmp_path / "real-overlay-storage",
        image=image,
    )

    assert capabilities.operating_system == "Linux"

    for interruption in (None, RuntimeError("failure"), KeyboardInterrupt()):
        workspace = OverlayQuotaWorkspace.create(
            storage_root=tmp_path / "real-overlay-storage",
            capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
            include_roots=("/app", "/etc/nginx"),
        )
        if interruption is None:
            with workspace:
                assert len(workspace.docker_mounts()) == 2
        else:
            with pytest.raises(type(interruption)):
                with workspace:
                    raise interruption
        assert not workspace.instance_dir.exists()
    assert not list((tmp_path / "real-overlay-storage").glob("securebench-overlay-*"))
