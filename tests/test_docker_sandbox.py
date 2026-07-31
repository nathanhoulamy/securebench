import subprocess
from types import SimpleNamespace

import pytest

from securebench.sandboxes import TIMEOUT_EXIT_CODE, DockerBindMount, DockerSandbox


def test_docker_sandbox_reuses_persistent_container_and_passes_env_names(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    seen = {"commands": [], "kwargs": []}

    def fake_run(command, **kwargs):
        seen["commands"].append(command)
        seen["kwargs"].append(kwargs)
        if command[:2] == ["docker", "run"]:
            return SimpleNamespace(returncode=0, stdout="container-id\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    sandbox = DockerSandbox(image="agent-image", root=tmp_path, env_names=("OPENAI_API_KEY",))
    result = sandbox.run(["python", "-m", "tool.run"], workdir="repo", timeout=3)
    sandbox.run(["python", "--version"], workdir="repo", timeout=4)
    sandbox.close()

    assert result.stdout == "ok"
    assert seen["commands"][0][:4] == ["docker", "run", "-d", "--name"]
    assert ["--entrypoint", ""] == seen["commands"][0][
        seen["commands"][0].index("--entrypoint") : seen["commands"][0].index("--entrypoint") + 2
    ]
    assert "--network" in seen["commands"][0]
    assert "none" in seen["commands"][0]
    assert ["--cap-drop", "ALL"] == seen["commands"][0][
        seen["commands"][0].index("--cap-drop") : seen["commands"][0].index("--cap-drop") + 2
    ]
    assert "--read-only" in seen["commands"][0]
    assert ["--tmpfs", "/tmp"] == seen["commands"][0][
        seen["commands"][0].index("--tmpfs") : seen["commands"][0].index("--tmpfs") + 2
    ]
    assert "--mount" not in seen["commands"][0]
    assert ["--memory", "1g"] == seen["commands"][0][
        seen["commands"][0].index("--memory") : seen["commands"][0].index("--memory") + 2
    ]
    assert ["--pids-limit", "256"] == seen["commands"][0][
        seen["commands"][0].index("--pids-limit") : seen["commands"][0].index("--pids-limit") + 2
    ]
    assert ["--security-opt", "no-new-privileges:true"] == seen["commands"][0][
        seen["commands"][0].index("--security-opt") : seen["commands"][0].index("--security-opt") + 2
    ]
    assert "-e" in seen["commands"][0]
    assert "OPENAI_API_KEY" in seen["commands"][0]
    assert "secret-value" not in seen["commands"][0]
    assert seen["commands"][1][:2] == ["docker", "exec"]
    assert seen["commands"][1][-3:] == ["python", "-m", "tool.run"]
    assert seen["commands"][2][:2] == ["docker", "exec"]
    assert seen["commands"][3][:3] == ["docker", "rm", "-f"]
    assert seen["kwargs"][1]["timeout"] == 3


def test_docker_sandbox_can_use_disposable_container_per_command(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    sandbox = DockerSandbox(image="agent-image", root=tmp_path, persistent=False)
    result = sandbox.run(["python", "--version"], timeout=3)

    assert result.stdout == "ok"
    assert seen["command"][:3] == ["docker", "run", "--rm"]
    assert ["--entrypoint", ""] == seen["command"][
        seen["command"].index("--entrypoint") : seen["command"].index("--entrypoint") + 2
    ]
    assert "--network" in seen["command"]
    assert "none" in seen["command"]
    assert "--read-only" in seen["command"]
    assert "--mount" not in seen["command"]
    assert seen["command"][-2:] == ["python", "--version"]


def test_docker_sandbox_allows_limit_overrides_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SECUREBENCH_DOCKER_MEM_LIMIT", "8g")
    monkeypatch.setenv("SECUREBENCH_DOCKER_PIDS_LIMIT", "1024")
    monkeypatch.setenv("SECUREBENCH_DOCKER_TMPFS", "/tmp:exec,size=2g;/run:size=64m")
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    sandbox = DockerSandbox(image="agent-image", root=tmp_path, persistent=False)
    sandbox.run(["python", "--version"])

    assert ["--memory", "8g"] == seen["command"][
        seen["command"].index("--memory") : seen["command"].index("--memory") + 2
    ]
    assert ["--pids-limit", "1024"] == seen["command"][
        seen["command"].index("--pids-limit") : seen["command"].index("--pids-limit") + 2
    ]
    tmpfs_indices = [index for index, value in enumerate(seen["command"]) if value == "--tmpfs"]
    assert [seen["command"][index + 1] for index in tmpfs_indices] == [
        "/tmp:exec,size=2g",
        "/run:size=64m",
    ]


def test_docker_sandbox_forwards_stdin(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr("subprocess.run", fake_run)

    sandbox = DockerSandbox(image="agent-image", root=tmp_path, persistent=False)
    result = sandbox.run(["git", "apply", "--binary"], stdin=b"trusted patch")

    assert seen["kwargs"]["input"] == b"trusted patch"
    assert seen["kwargs"]["text"] is False
    assert "-i" in seen["command"]
    assert result.stdout == "ok"


def test_docker_sandbox_attaches_stdin_to_persistent_container(monkeypatch, tmp_path):
    seen = {"commands": []}

    def fake_run(command, **kwargs):
        seen["commands"].append(command)
        if command[:2] == ["docker", "run"]:
            return SimpleNamespace(returncode=0, stdout="container-id\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    sandbox = DockerSandbox(image="agent-image", root=tmp_path)
    result = sandbox.run(["git", "apply", "--binary"], stdin="trusted patch")

    assert seen["commands"][1][:3] == ["docker", "exec", "-i"]
    assert result.stdout == "ok"


def test_docker_sandbox_rejects_stdin_for_streaming_agent_command(monkeypatch, tmp_path):
    monkeypatch.setattr("securebench.sandboxes.docker.wants_agent_output", lambda: True)
    sandbox = DockerSandbox(image="agent-image", root=tmp_path, persistent=False)

    with pytest.raises(ValueError, match="Streaming agent commands do not support stdin"):
        sandbox.run(["codex", "exec"], stdin="not supported")


def test_docker_sandbox_passes_explicit_environment_values(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    sandbox = DockerSandbox(
        image="agent-image",
        root=tmp_path,
        persistent=False,
        env={"HTTPS_PROXY": "http://proxy:8080"},
    )
    sandbox.run(["python", "--version"])

    assert ["-e", "HTTPS_PROXY=http://proxy:8080"] == seen["command"][
        seen["command"].index("-e") : seen["command"].index("-e") + 2
    ]


def test_docker_sandbox_run_reports_timeout_and_closes_persistent_container(monkeypatch, tmp_path):
    seen = {"commands": []}

    def fake_run(command, **kwargs):
        seen["commands"].append(command)
        if command[:2] == ["docker", "run"]:
            return SimpleNamespace(returncode=0, stdout="container-id\n", stderr="")
        if command[:2] == ["docker", "exec"]:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], output="partial out", stderr="partial err")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    sandbox = DockerSandbox(image="agent-image", root=tmp_path)
    result = sandbox.run(["sleep", "10"], timeout=2)

    assert result.exit_code == TIMEOUT_EXIT_CODE
    assert result.timed_out is True
    assert result.timeout_seconds == 2
    assert result.stdout == "partial out"
    assert result.stderr == "partial err"
    assert seen["commands"][0][:2] == ["docker", "run"]
    assert seen["commands"][1][:2] == ["docker", "exec"]
    assert seen["commands"][2][:3] == ["docker", "rm", "-f"]


def test_docker_sandbox_preserves_absolute_container_workdir(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    sandbox = DockerSandbox(image="agent-image", root=tmp_path, persistent=False)
    sandbox.run(["git", "status"], workdir="/testbed")

    assert seen["command"][seen["command"].index("-w") + 1] == "/testbed"


def test_docker_sandbox_can_mount_workspace_at_non_default_target(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    sandbox = DockerSandbox(
        image="agent-image",
        root=tmp_path,
        persistent=False,
        workspace_mount_target="/securebench-workspace",
    )
    sandbox.run(["git", "status"], workdir="/workspace/repo")

    assert f"{tmp_path}:/securebench-workspace" in seen["command"]
    assert seen["command"][seen["command"].index("-w") + 1] == "/workspace/repo"


def test_docker_sandbox_can_mount_workspace_at_app_target(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    sandbox = DockerSandbox(
        image="agent-image",
        root=tmp_path,
        persistent=False,
        workspace_mount_target="/app",
    )
    sandbox.run(["ls"], workdir="/app")

    assert f"{tmp_path}:/app" in seen["command"]
    assert seen["command"][seen["command"].index("-w") + 1] == "/app"


def test_docker_sandbox_resolves_relative_paths_against_workspace_target(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    source = tmp_path / "input.txt"
    source.write_text("data")

    sandbox = DockerSandbox(
        image="agent-image",
        root=tmp_path / "workspace",
        persistent=False,
        workspace_mount_target="/app",
        mounts=(DockerBindMount(source=source, target="input.txt", read_only=True),),
    )
    sandbox.run(["python", "--version"], workdir="subdir")

    mount_index = seen["command"].index("--mount")
    assert seen["command"][mount_index + 1] == f"type=bind,source={source},target=/app/input.txt,readonly"
    assert seen["command"][seen["command"].index("-w") + 1] == "/app/subdir"


def test_docker_sandbox_rejects_unsafe_workspace_mount_target(tmp_path):
    with pytest.raises(ValueError, match="workspace mount target"):
        DockerSandbox(
            image="agent-image",
            root=tmp_path,
            workspace_mount_target="/etc",
        )


def test_docker_sandbox_accepts_explicit_hardening_options(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    sandbox = DockerSandbox(
        image="agent-image",
        root=tmp_path,
        persistent=False,
        network="bridge",
        cap_drop=("NET_RAW",),
        read_only=False,
        tmpfs=("/tmp:size=64m",),
        mem_limit=None,
        pids_limit=None,
        security_opt=("label=disable",),
    )
    sandbox.run(["python", "--version"])

    assert ["--network", "bridge"] == seen["command"][
        seen["command"].index("--network") : seen["command"].index("--network") + 2
    ]
    assert ["--cap-drop", "NET_RAW"] == seen["command"][
        seen["command"].index("--cap-drop") : seen["command"].index("--cap-drop") + 2
    ]
    assert "--cap-add" not in seen["command"]
    assert "--read-only" not in seen["command"]
    assert "--memory" not in seen["command"]
    assert "--pids-limit" not in seen["command"]


def test_docker_sandbox_accepts_cap_add(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    sandbox = DockerSandbox(
        image="agent-image",
        root=tmp_path,
        persistent=False,
        cap_add=("SYS_CHROOT",),
    )
    sandbox.run(["python", "--version"])

    assert ["--cap-add", "SYS_CHROOT"] == seen["command"][
        seen["command"].index("--cap-add") : seen["command"].index("--cap-add") + 2
    ]


def test_docker_sandbox_rejects_invalid_env_names(tmp_path):
    sandbox = DockerSandbox(image="agent-image", root=tmp_path, env_names=("BAD=value",))

    with pytest.raises(ValueError, match="environment variable name"):
        sandbox.run(["python", "--version"])


def test_docker_sandbox_adds_read_only_bind_mounts(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    source = tmp_path / "input.txt"
    source.write_text("data")

    sandbox = DockerSandbox(
        image="agent-image",
        root=tmp_path / "workspace",
        persistent=False,
        mounts=(DockerBindMount(source=source, target="input.txt", read_only=True),),
    )
    sandbox.run(["python", "--version"])

    mount_index = seen["command"].index("--mount")
    assert seen["command"][mount_index + 1] == f"type=bind,source={source},target=/workspace/input.txt,readonly"
    assert ["-v", f"{sandbox.root}:/workspace"] == seen["command"][
        seen["command"].index("-v") : seen["command"].index("-v") + 2
    ]


def test_docker_sandbox_accepts_writable_bind_mounts(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    sandbox = DockerSandbox(
        image="agent-image",
        root=tmp_path / "workspace",
        persistent=False,
        mounts=(DockerBindMount(source=tmp_path / "output", target="/workspace/output", read_only=False),),
    )
    sandbox.run(["python", "--version"])

    mount_index = seen["command"].index("--mount")
    assert seen["command"][mount_index + 1] == f"type=bind,source={tmp_path / 'output'},target=/workspace/output"


def test_docker_sandbox_accepts_agent_overlay_bind_mounts(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    overlay = tmp_path / "overlay"
    overlay.mkdir()

    sandbox = DockerSandbox(
        image="agent-image",
        root=tmp_path / "workspace",
        persistent=False,
        mounts=(DockerBindMount(source=overlay, target="/opt/securebench/codex", read_only=True),),
    )
    sandbox.run(["codex", "--version"])

    mount_index = seen["command"].index("--mount")
    assert seen["command"][mount_index + 1] == f"type=bind,source={overlay},target=/opt/securebench/codex,readonly"


def test_docker_sandbox_rejects_invalid_bind_mount_targets(tmp_path):
    sandbox = DockerSandbox(
        image="agent-image",
        root=tmp_path,
        mounts=(DockerBindMount(source=tmp_path / "input.txt", target="../input.txt"),),
    )

    with pytest.raises(ValueError, match="bind mount target"):
        sandbox.run(["python", "--version"])


def test_docker_sandbox_read_file_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("host secret")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "workspace-output.txt").symlink_to(outside)
    sandbox = DockerSandbox(image="agent-image", root=root)

    with pytest.raises(ValueError, match="escape root"):
        sandbox.read_file("workspace-output.txt")


def test_docker_sandbox_extract_file_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"host secret")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "candidate.bin").symlink_to(outside)
    sandbox = DockerSandbox(image="agent-image", root=root)

    with pytest.raises(ValueError, match="escape root"):
        sandbox.extract_file("candidate.bin")


def test_docker_sandbox_write_file_rejects_symlink_escape(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("original")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "workspace-output.txt").symlink_to(outside)
    sandbox = DockerSandbox(image="agent-image", root=root)

    with pytest.raises(ValueError, match="escape root"):
        sandbox.write_file("workspace-output.txt", "modified")

    assert outside.read_text() == "original"
