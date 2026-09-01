from types import SimpleNamespace

import pytest

from securebench.errors import ConfigError
from securebench.harnesses.shared import agent_workspace_git_env


def task(workdir: str = "/app/personal-site"):
    return SimpleNamespace(environment=SimpleNamespace(workdir=workdir))


def test_agent_workspace_git_env_adds_only_the_exact_workdir():
    result = agent_workspace_git_env(task(), {"HTTPS_PROXY": "http://proxy"})

    assert result == {
        "HTTPS_PROXY": "http://proxy",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": "/app/personal-site",
    }


def test_agent_workspace_git_env_preserves_existing_entries():
    source = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "user.name",
        "GIT_CONFIG_VALUE_0": "SecureBench Agent",
    }

    result = agent_workspace_git_env(task(), source)

    assert result["GIT_CONFIG_COUNT"] == "2"
    assert result["GIT_CONFIG_KEY_0"] == "user.name"
    assert result["GIT_CONFIG_VALUE_0"] == "SecureBench Agent"
    assert result["GIT_CONFIG_KEY_1"] == "safe.directory"
    assert result["GIT_CONFIG_VALUE_1"] == "/app/personal-site"
    assert source["GIT_CONFIG_COUNT"] == "1"


def test_agent_workspace_git_env_adds_declared_directory_candidates():
    candidate = SimpleNamespace(
        files=(
            SimpleNamespace(kind="directory_tree", path="/app/repo"),
            SimpleNamespace(kind="regular_file", path="/app/secret.txt"),
        )
    )
    nested_task = SimpleNamespace(
        environment=SimpleNamespace(workdir="/app"),
        verification=SimpleNamespace(candidate=candidate),
    )

    result = agent_workspace_git_env(nested_task, {})

    assert result == {
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": "/app",
        "GIT_CONFIG_KEY_1": "safe.directory",
        "GIT_CONFIG_VALUE_1": "/app/repo",
    }


@pytest.mark.parametrize(
    "env",
    [
        {"GIT_CONFIG_COUNT": "-1"},
        {"GIT_CONFIG_COUNT": "not-a-number"},
        {"GIT_CONFIG_COUNT": "129"},
        {"GIT_CONFIG_COUNT": "1"},
        {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.name"},
        {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_VALUE_0": "Agent"},
        {"GIT_CONFIG_COUNT": "0", "GIT_CONFIG_KEY_0": "safe.directory"},
        {"GIT_CONFIG_COUNT": "0", "GIT_CONFIG_VALUE_0": "/app"},
        {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_2": "safe.directory"},
    ],
)
def test_agent_workspace_git_env_rejects_ambiguous_configuration(env):
    with pytest.raises(ConfigError, match="Git|GIT_CONFIG_COUNT"):
        agent_workspace_git_env(task(), env)
