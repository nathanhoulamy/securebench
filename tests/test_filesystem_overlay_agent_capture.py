from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

import securebench.candidates.overlay as overlay_module
from securebench.candidates import (
    CandidateCaptureError,
    CandidateProductionError,
    CandidateStore,
    OverlayAgentInfrastructureError,
    OverlayScanLimits,
    run_filesystem_overlay_agent_capture,
    scan_overlay_roots,
)
from securebench.candidates.overlay_agent import (
    OVERLAY_AGENT_INPUTS_TARGET,
    OVERLAY_AGENT_TMPFS,
    materialize_overlay_image_roots,
)
from securebench.sandboxes import CommandResult, DockerBindMount, DockerVolumeMount
from securebench.schemas.benchmark import FilesystemOverlayCandidate
from securebench.tester_config import MIN_OVERLAY_WORKSPACE_BYTES


BASELINE = "sha256:" + "1" * 64
IMAGE = "sha256:" + "2" * 64


@pytest.fixture(autouse=True)
def ignore_host_macos_provenance(monkeypatch: pytest.MonkeyPatch):
    if platform.system() == "Darwin":
        monkeypatch.setattr(overlay_module, "_has_extended_metadata", lambda path: False)


def local_limits() -> OverlayScanLimits:
    return OverlayScanLimits(required_uid=os.getuid(), required_gid=os.getgid())


def overlay_spec(**updates: object) -> FilesystemOverlayCandidate:
    value: dict[str, object] = {
        "type": "filesystem_overlay",
        "include_roots": ["/app", "/etc/nginx"],
        "max_changed_paths": 100,
        "max_changed_bytes": 1024 * 1024,
        "allow_internal_symlinks": True,
    }
    value.update(updates)
    return FilesystemOverlayCandidate.model_validate(value)


class FakeWorkspace:
    def __init__(self, root: Path, events: list[str]):
        self.include_roots = ("/app", "/etc/nginx")
        self.roots = {
            "/app": root / "app",
            "/etc/nginx": root / "nginx",
        }
        for path in self.roots.values():
            path.mkdir(parents=True)
        self.events = events
        self.closed = False
        self.host_root_calls = 0

    def host_roots(self):
        self.host_root_calls += 1
        if self.host_root_calls > 1:
            assert "sandbox_closed" in self.events
        return self.roots

    def docker_mounts(self, *, read_only=False):
        return tuple(
            DockerVolumeMount(
                source="securebench-test-volume",
                target=root,
                subpath=f"roots/{index:04d}",
                read_only=read_only,
            )
            for index, root in enumerate(self.include_roots)
        )

    def close(self):
        self.events.append("workspace_closed")
        self.closed = True


class FakeSandbox:
    def __init__(self, events, mutate, result, **options):
        self.events = events
        self.mutate = mutate
        self.result = result
        self.options = options

    def run(self, command, *, workdir, timeout):
        self.events.append("agent_run")
        self.mutate()
        return self.result

    def close(self):
        self.events.append("sandbox_closed")


def _successful_result(exit_code=0):
    return CommandResult(command=("agent",), exit_code=exit_code)


def test_direct_agent_capture_stops_before_scanning_and_cleans_everything(tmp_path: Path):
    events: list[str] = []
    workspace = FakeWorkspace(tmp_path / "quota", events)
    (workspace.roots["/app"] / "modify.txt").write_text("before")
    (workspace.roots["/app"] / "delete.txt").write_text("remove")
    (workspace.roots["/etc/nginx"] / "nginx.conf").write_text("old")
    trusted = tmp_path / "trusted-inputs"
    trusted.mkdir()
    (trusted / "task.json").write_text('{"instruction":"public"}\n')

    def materializer(image, staged, *, scan_limits):
        events.append("baseline_staged")
        return scan_overlay_roots(
            staged.include_roots,
            staged.host_roots(),
            limits=scan_limits,
            label="baseline",
        )

    def mutate():
        (workspace.roots["/app"] / "modify.txt").write_text("after")
        (workspace.roots["/app"] / "delete.txt").unlink()
        tool = workspace.roots["/app"] / "tool"
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o700)
        (workspace.roots["/app"] / "current").symlink_to("modify.txt")
        (workspace.roots["/etc/nginx"] / "nginx.conf").write_text("new")

    sandbox_options = {}

    def sandbox_factory(**options):
        sandbox_options.update(options)
        return FakeSandbox(events, mutate, _successful_result(), **options)

    store = CandidateStore(tmp_path / "store")
    result = run_filesystem_overlay_agent_capture(
        image=IMAGE,
        command=("agent",),
        workdir="/app",
        spec=overlay_spec(),
        store=store,
        baseline_digest=BASELINE,
        storage_root=tmp_path / "storage",
        capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
        trusted_inputs_root=trusted,
        scan_limits=local_limits(),
        _workspace_factory=lambda **options: workspace,
        _sandbox_factory=sandbox_factory,
        _materializer=materializer,
    )

    assert events == [
        "baseline_staged",
        "agent_run",
        "sandbox_closed",
        "workspace_closed",
    ]
    assert workspace.closed
    assert sandbox_options["read_only"] is True
    assert sandbox_options["workspace_read_only"] is True
    assert sandbox_options["workspace_mount_target"] == OVERLAY_AGENT_INPUTS_TARGET
    assert sandbox_options["tmpfs"] == OVERLAY_AGENT_TMPFS
    assert sandbox_options["allow_resource_overrides"] is False
    assert all(not mount.read_only for mount in sandbox_options["volume_mounts"])
    manifest = store.load_candidate(result.candidate.digest)
    changes = {(row["root"], row["path"]): row for row in manifest.payload["changes"]}
    assert changes[("/app", "delete.txt")]["kind"] == "absent"
    assert changes[("/app", "tool")]["mode"] == 0o755
    assert changes[("/app", "current")]["target"] == "modify.txt"
    assert changes[("/etc/nginx", "nginx.conf")]["kind"] == "regular_file"
    assert not any(row["path"] == "task.json" for row in manifest.payload["changes"])


@pytest.mark.parametrize("failure", ["agent", "capture", "baseline"])
def test_agent_failure_baseline_mismatch_and_capture_rejection_cleanup(
    tmp_path: Path, failure: str
):
    events: list[str] = []
    workspace = FakeWorkspace(tmp_path / "quota", events)
    (workspace.roots["/app"] / "value").write_text("before")
    trusted = tmp_path / "trusted"
    trusted.mkdir()

    def materializer(image, staged, *, scan_limits):
        baseline = scan_overlay_roots(
            staged.include_roots,
            staged.host_roots(),
            limits=scan_limits,
            label="baseline",
        )
        if failure == "baseline":
            baseline["/app"] = replace(baseline["/app"], path="/wrong")
        return baseline

    def mutate():
        if failure == "capture":
            (workspace.roots["/app"] / "escape").symlink_to("../../outside")

    exit_code = 9 if failure == "agent" else 0
    store = CandidateStore(tmp_path / "store")

    expected = CandidateProductionError if failure == "agent" else CandidateCaptureError
    with pytest.raises(expected):
        run_filesystem_overlay_agent_capture(
            image=IMAGE,
            command=("agent",),
            workdir="/app",
            spec=overlay_spec(),
            store=store,
            baseline_digest=BASELINE,
            storage_root=tmp_path / "storage",
            capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
            trusted_inputs_root=trusted,
            scan_limits=local_limits(),
            _workspace_factory=lambda **options: workspace,
            _sandbox_factory=lambda **options: FakeSandbox(
                events, mutate, _successful_result(exit_code), **options
            ),
            _materializer=materializer,
        )

    assert events[-2:] == ["sandbox_closed", "workspace_closed"]
    assert workspace.closed
    assert not any(path.is_file() for path in store.candidates_root.rglob("*"))


def test_baseline_materialization_failure_still_destroys_workspace(tmp_path: Path):
    events: list[str] = []
    workspace = FakeWorkspace(tmp_path / "quota", events)
    trusted = tmp_path / "trusted"
    trusted.mkdir()

    def fail_materialization(image, staged, *, scan_limits):
        raise OverlayAgentInfrastructureError("injected baseline failure")

    with pytest.raises(OverlayAgentInfrastructureError, match="injected"):
        run_filesystem_overlay_agent_capture(
            image=IMAGE,
            command=("agent",),
            workdir="/app",
            spec=overlay_spec(),
            store=CandidateStore(tmp_path / "store"),
            baseline_digest=BASELINE,
            storage_root=tmp_path / "storage",
            capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
            trusted_inputs_root=trusted,
            _workspace_factory=lambda **options: workspace,
            _materializer=fail_materialization,
        )

    assert events == ["workspace_closed"]


def test_harness_preflight_failure_stops_container_and_destroys_workspace(tmp_path: Path):
    events: list[str] = []
    workspace = FakeWorkspace(tmp_path / "quota", events)
    (workspace.roots["/app"] / "value").write_text("before")
    trusted = tmp_path / "trusted"
    trusted.mkdir()

    def materializer(image, staged, *, scan_limits):
        return scan_overlay_roots(
            staged.include_roots,
            staged.host_roots(),
            limits=scan_limits,
            label="baseline",
        )

    with pytest.raises(OverlayAgentInfrastructureError, match="preflight failed"):
        run_filesystem_overlay_agent_capture(
            image=IMAGE,
            command=("agent",),
            preflight_command=("agent", "--version"),
            workdir="/app",
            spec=overlay_spec(),
            store=CandidateStore(tmp_path / "store"),
            baseline_digest=BASELINE,
            storage_root=tmp_path / "storage",
            capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
            trusted_inputs_root=trusted,
            scan_limits=local_limits(),
            _workspace_factory=lambda **options: workspace,
            _sandbox_factory=lambda **options: FakeSandbox(
                events,
                lambda: None,
                _successful_result(exit_code=9),
                **options,
            ),
            _materializer=materializer,
        )

    assert events[-2:] == ["sandbox_closed", "workspace_closed"]


def test_interruption_stops_container_and_destroys_workspace(tmp_path: Path):
    events: list[str] = []
    workspace = FakeWorkspace(tmp_path / "quota", events)
    (workspace.roots["/app"] / "value").write_text("before")
    trusted = tmp_path / "trusted"
    trusted.mkdir()

    def materializer(image, staged, *, scan_limits):
        return scan_overlay_roots(
            staged.include_roots,
            staged.host_roots(),
            limits=scan_limits,
            label="baseline",
        )

    class InterruptedSandbox(FakeSandbox):
        def run(self, command, *, workdir, timeout):
            self.events.append("agent_run")
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_filesystem_overlay_agent_capture(
            image=IMAGE,
            command=("agent",),
            workdir="/app",
            spec=overlay_spec(),
            store=CandidateStore(tmp_path / "store"),
            baseline_digest=BASELINE,
            storage_root=tmp_path / "storage",
            capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
            trusted_inputs_root=trusted,
            scan_limits=local_limits(),
            _workspace_factory=lambda **options: workspace,
            _sandbox_factory=lambda **options: InterruptedSandbox(
                events,
                lambda: None,
                _successful_result(),
                **options,
            ),
            _materializer=materializer,
        )

    assert events[-2:] == ["sandbox_closed", "workspace_closed"]


def test_materializer_copies_each_root_then_removes_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    events: list[str] = []
    workspace = FakeWorkspace(tmp_path / "quota", events)
    commands = []

    def fake_run(command, *, timeout):
        commands.append(tuple(command))
        if command[:3] == ["docker", "cp", "--archive"]:
            destination = Path(command[-1])
            (destination / "baseline.txt").write_text(command[-2])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(
        "securebench.candidates.overlay_agent._run_materializer",
        fake_run,
    )

    baseline = materialize_overlay_image_roots(
        IMAGE,
        workspace,
        scan_limits=local_limits(),
    )

    assert set(baseline) == {"/app", "/etc/nginx"}
    assert [command[:3] for command in commands] == [
        ("docker", "create", "--name"),
        ("docker", "cp", "--archive"),
        ("docker", "cp", "--archive"),
        ("docker", "rm", "-f"),
    ]


def test_agent_mount_plan_rejects_writable_or_framework_colliding_inputs(tmp_path: Path):
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    public = tmp_path / "public"
    public.mkdir()
    common = {
        "image": IMAGE,
        "command": ("agent",),
        "workdir": "/app",
        "spec": overlay_spec(),
        "store": CandidateStore(tmp_path / "store"),
        "baseline_digest": BASELINE,
        "storage_root": tmp_path / "storage",
        "capacity_bytes": MIN_OVERLAY_WORKSPACE_BYTES,
        "trusted_inputs_root": trusted,
    }

    with pytest.raises(OverlayAgentInfrastructureError, match="read-only"):
        run_filesystem_overlay_agent_capture(
            **common,
            public_mounts=(DockerBindMount(public, "/app/assets", read_only=False),),
        )
    with pytest.raises(OverlayAgentInfrastructureError, match="framework-owned"):
        run_filesystem_overlay_agent_capture(
            **common,
            public_mounts=(
                DockerBindMount(public, OVERLAY_AGENT_INPUTS_TARGET, read_only=True),
            ),
        )


@pytest.mark.skipif(
    os.environ.get("SECUREBENCH_RUN_REAL_DOCKER_OVERLAY_TESTS") != "1",
    reason="requires an explicitly provisioned root Linux Docker host",
)
def test_real_docker_agent_capture_and_cleanup(tmp_path: Path):
    if platform.system() != "Linux" or os.geteuid() != 0:
        pytest.skip("requires a root Linux host")
    base = os.environ.get("SECUREBENCH_OVERLAY_PROBE_IMAGE")
    if base is None:
        pytest.skip("SECUREBENCH_OVERLAY_PROBE_IMAGE must be a local pinned Python image")
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        f"FROM {base}\n"
        "RUN mkdir -p /app /etc/nginx && printf before > /app/value "
        "&& printf remove > /app/delete && printf old > /etc/nginx/nginx.conf\n"
    )
    built = subprocess.run(
        ["docker", "build", "--quiet", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    image = built.stdout.strip()
    if not image.startswith("sha256:"):
        pytest.fail("Docker build did not return a pinned image ID")
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    (trusted / "task.json").write_text("{}\n")
    storage = tmp_path / "overlay-storage"
    store = CandidateStore(tmp_path / "store")
    before_volumes = sorted(
        subprocess.run(
            [
                "docker",
                "volume",
                "ls",
                "--quiet",
                "--filter",
                "label=securebench.overlay-workspace=true",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    try:
        result = run_filesystem_overlay_agent_capture(
            image=image,
            command=(
                "python",
                "-c",
                "from pathlib import Path; import os; "
                "Path('/app/value').write_text('after'); Path('/app/delete').unlink(); "
                "Path('/app/tool').write_text('run'); os.chmod('/app/tool', 0o700); "
                "Path('/app/current').symlink_to('value'); "
                "Path('/etc/nginx/nginx.conf').write_text('new')",
            ),
            workdir="/app",
            spec=overlay_spec(),
            store=store,
            baseline_digest=BASELINE,
            storage_root=storage,
            capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
            trusted_inputs_root=trusted,
        )
        assert store.load_candidate(result.candidate.digest).payload["changed_paths"] == 5

        with pytest.raises(CandidateProductionError):
            run_filesystem_overlay_agent_capture(
                image=image,
                command=("python", "-c", "raise SystemExit(9)"),
                workdir="/app",
                spec=overlay_spec(),
                store=store,
                baseline_digest=BASELINE,
                storage_root=storage,
                capacity_bytes=MIN_OVERLAY_WORKSPACE_BYTES,
                trusted_inputs_root=trusted,
            )
    finally:
        remaining_containers = subprocess.run(
            [
                "docker",
                "container",
                "ls",
                "--all",
                "--quiet",
                "--filter",
                f"ancestor={image}",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        subprocess.run(
            ["docker", "image", "rm", "--force", image],
            check=False,
            capture_output=True,
            text=True,
        )
    assert remaining_containers == []

    after_volumes = sorted(
        subprocess.run(
            [
                "docker",
                "volume",
                "ls",
                "--quiet",
                "--filter",
                "label=securebench.overlay-workspace=true",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )
    assert after_volumes == before_volumes
    assert not list(storage.glob("securebench-overlay-*"))
