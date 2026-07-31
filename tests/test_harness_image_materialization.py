from types import SimpleNamespace

import pytest

from securebench.benchmark_compiler import compile_benchmark_row
from securebench.benchmark_pack import BenchmarkPackManifest, BenchmarkRow
from securebench.errors import ConfigError
from securebench.harnesses.shared import (
    ensure_environment_image,
    materialize_workdir_from_image_if_requested,
)


def terminal_task(environment, *, manifest_path=None):
    return compile_benchmark_row(
        BenchmarkRow(
            id="terminal-1",
            family="terminal_task",
            input={"instructions": "Edit files in the terminal workspace."},
            eval={"checker": {"source": "pytest", "path": "checks"}},
            environment=environment,
        ),
        manifest=BenchmarkPackManifest(id="pack", version=1, path=manifest_path),
    )


def test_image_workdir_materialization_is_opt_in(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("securebench.harnesses.shared.subprocess.run", fake_run)

    copied = materialize_workdir_from_image_if_requested(
        terminal_task({"image": "example/task:latest", "workdir": "/app"}),
        tmp_path,
    )

    assert copied is False
    assert calls == []


def test_image_workdir_materialization_copies_container_workdir(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("securebench.harnesses.shared.subprocess.run", fake_run)

    copied = materialize_workdir_from_image_if_requested(
        terminal_task(
            {
                "image": "example/task:latest",
                "workdir": "/app",
                "materialize_workdir_from_image": True,
            }
        ),
        tmp_path,
    )

    assert copied is True
    assert calls[0][:4] == ["docker", "create", "--name", calls[0][3]]
    assert calls[0][-1] == "example/task:latest"
    assert calls[1] == ["docker", "cp", f"{calls[0][3]}:/app/.", str(tmp_path)]
    assert calls[2] == ["docker", "rm", "-f", calls[0][3]]


def test_image_workdir_materialization_builds_missing_pack_local_image(tmp_path, monkeypatch):
    context = tmp_path / "docker" / "task-1"
    context.mkdir(parents=True)
    (context / "Dockerfile").write_text("FROM scratch\n")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("id: pack\nversion: 1\n")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=1 if command[:3] == ["docker", "image", "inspect"] else 0,
            stdout="",
            stderr="missing" if command[:3] == ["docker", "image", "inspect"] else "",
        )

    monkeypatch.setattr("securebench.harnesses.shared.subprocess.run", fake_run)

    copied = materialize_workdir_from_image_if_requested(
        terminal_task(
            {
                "build_context": "docker/task-1",
                "image": "example/task:latest",
                "workdir": "/app",
                "materialize_workdir_from_image": True,
            },
            manifest_path=manifest,
        ),
        tmp_path / "workspace",
    )

    assert copied is True
    assert calls[0] == ["docker", "image", "inspect", "example/task:latest"]
    assert calls[1] == [
        "docker",
        "build",
        "--tag",
        "example/task:latest",
        str(context),
    ]
    assert calls[2][0:2] == ["docker", "create"]


def test_ensure_environment_image_skips_build_when_image_exists(tmp_path, monkeypatch):
    context = tmp_path / "docker" / "task-1"
    context.mkdir(parents=True)
    (context / "Dockerfile").write_text("FROM scratch\n")
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text("id: pack\nversion: 1\n")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr("securebench.harnesses.shared.subprocess.run", fake_run)
    task = terminal_task(
        {
            "build_context": "docker/task-1",
            "image": "example/task:latest",
        },
        manifest_path=manifest,
    )

    assert ensure_environment_image(task) is False
    assert calls == [["docker", "image", "inspect", "example/task:latest"]]


def test_ensure_environment_image_rejects_context_outside_pack(tmp_path):
    manifest = tmp_path / "pack" / "manifest.yaml"
    manifest.parent.mkdir()
    manifest.write_text("id: pack\nversion: 1\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "Dockerfile").write_text("FROM scratch\n")
    task = terminal_task(
        {
            "build_context": "../outside",
            "image": "example/task:latest",
        },
        manifest_path=manifest,
    )

    with pytest.raises(ConfigError, match="escapes the benchmark pack"):
        ensure_environment_image(task)


def test_image_workdir_materialization_removes_container_on_copy_failure(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[:2] == ["docker", "cp"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="copy failed")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("securebench.harnesses.shared.subprocess.run", fake_run)

    with pytest.raises(ConfigError, match="failed to materialize"):
        materialize_workdir_from_image_if_requested(
            terminal_task(
                {
                    "image": "example/task:latest",
                    "workdir": "/app",
                    "materialize_workdir_from_image": True,
                }
            ),
            tmp_path,
        )

    assert calls[0][0:2] == ["docker", "create"]
    assert calls[1][0:2] == ["docker", "cp"]
    assert calls[2] == ["docker", "rm", "-f", calls[0][3]]


def test_image_workdir_materialization_rejects_non_boolean(tmp_path):
    with pytest.raises(ConfigError, match="materialize_workdir_from_image"):
        materialize_workdir_from_image_if_requested(
            terminal_task(
                {
                    "image": "example/task:latest",
                    "workdir": "/app",
                    "materialize_workdir_from_image": "yes",
                }
            ),
            tmp_path,
        )
