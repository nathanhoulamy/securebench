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
    result = sandbox.run(["python", "-m", "securebench.agent.run"], workdir="repo", timeout=3)
    sandbox.run(["python", "--version"], workdir="repo", timeout=4)
    sandbox.close()

    assert result.stdout == "ok"
    assert seen["commands"][0][:4] == ["docker", "run", "-d", "--name"]
    assert "-e" in seen["commands"][0]
    assert "OPENAI_API_KEY" in seen["commands"][0]
    assert "secret-value" not in seen["commands"][0]
    assert seen["commands"][1][:2] == ["docker", "exec"]
    assert seen["commands"][1][-3:] == ["python", "-m", "securebench.agent.run"]
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
    assert seen["command"][-2:] == ["python", "--version"]


def test_docker_sandbox_rejects_invalid_env_names(tmp_path):
    sandbox = DockerSandbox(image="agent-image", root=tmp_path, env_names=("BAD=value",))

    with pytest.raises(ValueError, match="environment variable name"):
        sandbox.run(["python", "--version"])
