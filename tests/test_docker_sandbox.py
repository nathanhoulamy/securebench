from types import SimpleNamespace

import pytest

from securebench.sandboxes import DockerSandbox


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
    result = sandbox.run(["python", "-m", "securebench_agent.run"], workdir="repo", timeout=3)
    sandbox.run(["python", "--version"], workdir="repo", timeout=4)
    sandbox.close()

    assert result.stdout == "ok"
    assert seen["commands"][0][:4] == ["docker", "run", "-d", "--name"]
    assert "--network" in seen["commands"][0]
    assert "none" in seen["commands"][0]
    assert ["--cap-drop", "ALL"] == seen["commands"][0][
        seen["commands"][0].index("--cap-drop") : seen["commands"][0].index("--cap-drop") + 2
    ]
    assert "--read-only" in seen["commands"][0]
    assert ["--tmpfs", "/tmp"] == seen["commands"][0][
        seen["commands"][0].index("--tmpfs") : seen["commands"][0].index("--tmpfs") + 2
    ]
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
    assert seen["commands"][1][-3:] == ["python", "-m", "securebench_agent.run"]
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
    assert "--network" in seen["command"]
    assert "none" in seen["command"]
    assert "--read-only" in seen["command"]
    assert seen["command"][-2:] == ["python", "--version"]


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
    assert "--read-only" not in seen["command"]
    assert "--memory" not in seen["command"]
    assert "--pids-limit" not in seen["command"]


def test_docker_sandbox_rejects_invalid_env_names(tmp_path):
    sandbox = DockerSandbox(image="agent-image", root=tmp_path, env_names=("BAD=value",))

    with pytest.raises(ValueError, match="environment variable name"):
        sandbox.run(["python", "--version"])
