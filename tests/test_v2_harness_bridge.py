from hashlib import sha256
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from securebench.benchmark_compiler import compile_benchmark_pack
from securebench.benchmark_pack import load_benchmark_pack
from securebench.errors import ConfigError
from securebench.harnesses.command import CommandHarnessProducer
from securebench.harnesses.shared import (
    materialize_image_workdir,
    reject_git_patch_framework_collisions,
    reject_task_file_collision,
    workspace_dir_name,
)
from securebench.sandboxes import CommandResult
from securebench.schemas.benchmark import GitPatchCandidate
from securebench.workspaces.materialization import MaterializationPlan, MaterializedResource


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "benchmarks" / "terminal-bench"


class FakeDockerSandbox:
    instances = []

    def __init__(self, *, root, image, mounts=(), **kwargs):
        self.root = Path(root)
        self.image = image
        self.mounts = tuple(mounts)
        self.kwargs = kwargs
        self.commands = []
        self.closed = False
        self.__class__.instances.append(self)

    def run(self, command, *, workdir=None, timeout=None):
        self.commands.append((command, workdir, timeout))
        return CommandResult(tuple(command), 0, "agent log", "")

    def close(self):
        self.closed = True


def compiled_task():
    return next(
        compile_benchmark_pack(
            load_benchmark_pack(PACK / "manifest-v2.yaml", PACK / "tasks-v2.jsonl")
        )
    )


def test_command_harness_exposes_ephemeral_workspace_for_declared_capture(monkeypatch, tmp_path):
    FakeDockerSandbox.instances = []
    monkeypatch.setattr("securebench.harnesses.command.DockerSandbox", FakeDockerSandbox)
    monkeypatch.setattr(
        "securebench.harnesses.command.materialize_image_workdir",
        lambda task, destination: None,
    )

    task = compiled_task()
    production = CommandHarnessProducer(
        command=("produce",),
        workspace_root=tmp_path,
    ).produce(task)

    assert production.workspace == str(tmp_path / workspace_dir_name(task))
    assert production.metadata["candidate_type"] == "file_bundle"
    sandbox = FakeDockerSandbox.instances[-1]
    assert sandbox.commands == [(('produce',), "/app", 1200.0)]
    assert sandbox.closed is True
    assert len(sandbox.mounts) == 3
    assert not any("oracle" in str(mount.source) for mount in sandbox.mounts)
    assert all(not Path(mount.source).is_relative_to(Path(production.workspace)) for mount in sandbox.mounts)


def test_command_harness_requires_persistent_stopped_state_workspace():
    with pytest.raises(ConfigError, match="persistent workspace_root"):
        CommandHarnessProducer(command=("produce",)).produce(compiled_task())


def test_workspace_directory_names_are_bounded_and_collision_resistant():
    original = compiled_task()
    long_id = "a" * 512
    first = original.__class__(**{**original.__dict__, "id": long_id})
    second = original.__class__(**{**original.__dict__, "id": long_id[:-1] + "b"})

    first_name = workspace_dir_name(first)
    second_name = workspace_dir_name(second)

    assert len(first_name.encode("utf-8")) < 255
    assert first_name != second_name
    assert first_name.endswith("-" + sha256(long_id.encode()).hexdigest())


@pytest.mark.parametrize("container_path", ["/app/task.json", "/app/Task.JSON"])
def test_task_file_collision_uses_file_resource_container_mount_path(container_path):
    plan = MaterializationPlan(
        component="agent",
        resources=(
            MaterializedResource(
                name="asset.0",
                visibility="public",
                kind="file",
                component="agent",
                relative_path="securebench/public/files/asset.0",
                serialization="mount",
                source_path="/pack/input.json",
                container_path=container_path,
                read_only=True,
            ),
        ),
    )

    with pytest.raises(ConfigError, match="task_file collides"):
        reject_task_file_collision(
            "task.json",
            plan,
            workspace_mount_target="/app",
        )


def test_image_materialization_surfaces_container_cleanup_failure(monkeypatch, tmp_path):
    def fake_run(command, **kwargs):
        if command[:2] == ["docker", "create"]:
            return SimpleNamespace(returncode=0, stdout="container", stderr="")
        if command[:2] == ["docker", "cp"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="daemon failure")
        raise AssertionError(command)

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(ConfigError, match="remove image materialization"):
        materialize_image_workdir(compiled_task(), tmp_path / "workspace")


def test_image_materialization_bounds_docker_create_and_cleanup(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[:2] == ["docker", "create"]:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if command[:3] == ["docker", "rm", "-f"]:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="No such container",
            )
        raise AssertionError(command)

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(ConfigError, match="create image materialization"):
        materialize_image_workdir(compiled_task(), tmp_path / "workspace")

    assert calls[0][1]["timeout"] == 120.0
    assert calls[1][1]["timeout"] == 30.0


def test_git_patch_image_materialization_requires_exact_clean_commit(monkeypatch, tmp_path):
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=baseline, check=True)
    subprocess.run(
        ["git", "config", "user.email", "securebench@example.invalid"],
        cwd=baseline,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "SecureBench"], cwd=baseline, check=True
    )
    (baseline / "README.md").write_text("baseline\n")
    subprocess.run(["git", "add", "."], cwd=baseline, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "baseline"], cwd=baseline, check=True
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=baseline,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    task = SimpleNamespace(
        environment=SimpleNamespace(image="sha256:" + "1" * 64, workdir="/app"),
        verification=SimpleNamespace(
            candidate=GitPatchCandidate.model_validate(
                {
                    "type": "git_patch",
                    "max_patch_bytes": 1024,
                    "max_changed_files": 1,
                    "max_changed_bytes": 1024,
                }
            )
        ),
        input={"base_commit": "f" * 40},
    )
    original_run = subprocess.run

    def fake_run(command, **kwargs):
        if command[:2] == ["docker", "create"]:
            return SimpleNamespace(returncode=0, stdout="container", stderr="")
        if command[:2] == ["docker", "cp"]:
            shutil.copytree(baseline, Path(command[-1]), dirs_exist_ok=True, symlinks=True)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if command[:3] == ["docker", "rm", "-f"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return original_run(command, **kwargs)

    monkeypatch.setattr("securebench.harnesses.shared.subprocess.run", fake_run)

    with pytest.raises(ConfigError, match="commit mismatch"):
        materialize_image_workdir(task, tmp_path / "workspace")

    task.input["base_commit"] = commit
    (baseline / "untracked.txt").write_text("dirty")
    with pytest.raises(ConfigError, match="must be clean"):
        materialize_image_workdir(task, tmp_path / "dirty-workspace")


def test_git_patch_harness_rejects_framework_paths_in_baseline(tmp_path):
    task = SimpleNamespace(
        verification=SimpleNamespace(
            candidate=GitPatchCandidate.model_validate(
                {
                    "type": "git_patch",
                    "max_patch_bytes": 1024,
                    "max_changed_files": 1,
                    "max_changed_bytes": 1024,
                }
            )
        )
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "task.json").write_text("baseline")

    with pytest.raises(ConfigError, match="framework-owned path: task.json"):
        reject_git_patch_framework_collisions(task, workspace, task_file="task.json")

    (workspace / "task.json").unlink()
    (workspace / "Task.JSON").write_text("baseline")

    with pytest.raises(ConfigError, match="framework-owned path: task.json"):
        reject_git_patch_framework_collisions(task, workspace, task_file="task.json")
