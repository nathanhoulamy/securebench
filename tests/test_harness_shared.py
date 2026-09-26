from types import SimpleNamespace

import pytest

from securebench.errors import ConfigError
from securebench.harnesses.claude_code import (
    claude_code_agent_command,
    claude_code_agent_env,
    claude_code_config,
    claude_code_overlay_shell_command,
    claude_code_shell_command,
)
from securebench.harnesses.codex import codex_config, codex_overlay_shell_command, codex_shell_command
from securebench.harnesses.shared import agent_prompt, agent_workspace_git_env


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


def prompt_task(instructions):
    return SimpleNamespace(id="pack/row", agent_payload=lambda: {"instructions": instructions})


def test_instructions_prompt_is_the_public_instruction_verbatim():
    text = "Line one.\n\n  - `code` stays\nLast line."

    assert agent_prompt(prompt_task(text), "task.json", "instructions") == text


@pytest.mark.parametrize("instructions", [None, "", "   "])
def test_instructions_prompt_rejects_missing_instructions(instructions):
    with pytest.raises(ConfigError, match="requires public instructions"):
        agent_prompt(prompt_task(instructions), "task.json", "instructions")


def test_codex_config_prompt_defaults_to_task_file_and_rejects_unknown_modes():
    base = {"model": "m"}

    assert codex_config(base)["prompt"] == "task_file"
    assert codex_config({**base, "prompt": "instructions"})["prompt"] == "instructions"
    with pytest.raises(ConfigError, match="harness.config.prompt"):
        codex_config({**base, "prompt": "verbatim"})


def test_claude_code_config_accepts_effort_and_prompt_modes():
    base = {"model": "m"}

    assert claude_code_config(base)["effort"] is None
    assert claude_code_config(base)["prompt"] == "task_file"
    config = claude_code_config({**base, "effort": "medium", "prompt": "instructions"})
    assert (config["effort"], config["prompt"]) == ("medium", "instructions")
    with pytest.raises(ConfigError, match="harness.config.effort"):
        claude_code_config({**base, "effort": "extreme"})
    with pytest.raises(ConfigError, match="harness.config.prompt"):
        claude_code_config({**base, "prompt": "verbatim"})


def test_claude_code_agent_command_passes_effort_and_separates_the_prompt():
    command = claude_code_agent_command("claude-sonnet-5", "medium", "-x; rm -rf /")

    assert "--model claude-sonnet-5 --effort medium " in command
    assert command.endswith("-- '-x; rm -rf /'")
    assert "--effort" not in claude_code_agent_command("m", None, "p")


def test_claude_code_agent_env_marks_the_sandbox_and_keeps_only_dummy_credentials():
    env = claude_code_agent_env({}, "http://relay:1", (), auth="subscription")

    assert env["IS_SANDBOX"] == "1"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"].startswith("sk-ant-oat01-securebench-dummy")
    assert "ANTHROPIC_API_KEY" not in env


@pytest.mark.parametrize(
    ("command", "state_env"),
    [
        (claude_code_shell_command("claude --version"), "CLAUDE_CONFIG_DIR"),
        (codex_shell_command("codex --version"), "CODEX_HOME"),
    ],
)
def test_agent_keeps_the_image_home_and_moves_only_its_own_state(command, state_env):
    # Images keep git identity and toolchains in HOME (fix-git's ~/.gitconfig,
    # DeepSWE's ~/go and ~/.rustup); upstream harnesses leave HOME alone.
    assert "export HOME=" not in command
    assert f"export {state_env}=/opt/securebench/" in command


def test_overlay_agent_still_moves_home_off_the_read_only_root():
    assert "export HOME=/tmp/securebench-claude-home;" in claude_code_overlay_shell_command("claude")
    assert "export HOME=/tmp/securebench-codex-home;" in codex_overlay_shell_command("codex", auth_seed=None)
