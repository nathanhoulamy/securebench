import pytest

from securebench.candidates import StaticCandidateProducer, TextCompletionProducer, WorkspaceAgentPatchProducer
from securebench.config import ConfigError, load_run_config, parse_run_config
from securebench.datasets import HUMANEVAL_DATASET_ID, MMLU_DATASET_ID, SWEBENCH_VERIFIED_DATASET_ID
from securebench.runners import CodeGenerationRunner, GitHubPatchRunner, MultipleChoiceRunner


def valid_config(**overrides):
    config = {
        "schema_version": "0.1",
        "run": {
            "id": "mmlu-test",
            "limit": 2,
            "output_path": "runs/mmlu-test/results.jsonl",
        },
        "dataset": {
            "provider": "huggingface",
            "name": MMLU_DATASET_ID,
            "config": "abstract_algebra",
            "split": "test",
            "streaming": True,
        },
        "adapter": {
            "id": "mmlu",
        },
        "producer": {
            "type": "static",
            "config": {
                "text": "A",
            },
        },
        "runner": {
            "type": "multiple_choice",
        },
    }
    config.update(overrides)
    return config


def test_parse_run_config_builds_dataset_ref_and_runtime_objects():
    config = parse_run_config(valid_config())

    assert config.run.id == "mmlu-test"
    assert config.run.limit == 2
    assert config.dataset_ref().name == MMLU_DATASET_ID
    assert config.dataset_ref().config == "abstract_algebra"
    assert config.build_adapter().benchmark_id == "mmlu"
    assert isinstance(config.build_producer(), StaticCandidateProducer)
    assert isinstance(config.build_runner(), MultipleChoiceRunner)
    assert config.sandbox.defaults.network == "none"
    assert config.sandbox.test_sandbox.read_only is True


def test_parse_run_config_builds_openai_compatible_producer():
    data = valid_config(
        producer={
            "type": "openai_compatible",
            "config": {
                "model": "gpt-4o-mini",
                "base_url": "https://api.openai.com/v1",
                "api_key_env": "OPENAI_API_KEY",
                "temperature": 0,
            },
        }
    )

    config = parse_run_config(data)

    assert isinstance(config.build_producer(), TextCompletionProducer)


def test_parse_run_config_builds_workspace_agent_patch_producer():
    data = valid_config(
        dataset={
            "provider": "huggingface",
            "name": SWEBENCH_VERIFIED_DATASET_ID,
            "split": "test",
            "streaming": True,
        },
        adapter={"id": "swebench_verified"},
        producer={
            "type": "workspace_agent_patch",
            "config": {
                "image": "securebench-agent:latest",
                "model": "test-model",
                "base_url": "https://llm.example/v1",
                "api_key_env": "TEST_API_KEY",
                "repo_dir": "worktree",
                "task_file": "TASK.md",
                "max_steps": 3,
                "max_tool_output": 2048,
                "command_timeout": 9,
                "request_timeout": 10,
                "timeout": 11,
                "temperature": 0,
                "setup_commands": ["python -m pip install pytest"],
                "allow_commands": ["git", "pytest"],
                "deny_commands": ["curl"],
            },
        },
        runner={"type": "github_patch"},
    )

    config = parse_run_config(data)
    producer = config.build_producer()

    assert isinstance(producer, WorkspaceAgentPatchProducer)
    assert config.producer.type == "workspace_agent_patch"
    sandbox = producer.sandbox_factory()
    assert sandbox.env_names == ("TEST_API_KEY",)
    assert sandbox.network == "none"
    assert sandbox.cap_drop == ("ALL",)
    assert sandbox.read_only is True
    sandbox.close()
    assert producer.setup_commands == ("python -m pip install pytest",)


def test_workspace_agent_patch_replay_config_does_not_pass_api_key_env():
    data = valid_config(
        dataset={
            "provider": "huggingface",
            "name": SWEBENCH_VERIFIED_DATASET_ID,
            "split": "test",
            "streaming": True,
        },
        adapter={"id": "swebench_verified"},
        producer={
            "type": "workspace_agent_patch",
            "config": {
                "replay_file": "/workspace/replay.json",
            },
        },
        runner={"type": "github_patch"},
    )

    producer = parse_run_config(data).build_producer()

    assert isinstance(producer, WorkspaceAgentPatchProducer)
    sandbox = producer.sandbox_factory()
    assert sandbox.env_names == ()
    sandbox.close()


def test_parse_run_config_builds_github_patch_runner_with_config():
    data = valid_config(
        dataset={
            "provider": "huggingface",
            "name": SWEBENCH_VERIFIED_DATASET_ID,
            "split": "test",
            "streaming": True,
        },
        adapter={"id": "swebench_verified"},
        producer={
            "type": "workspace_agent_patch",
            "config": {
                "replay_file": "/workspace/replay.json",
            },
        },
        runner={
            "type": "github_patch",
            "config": {
                "image": "securebench-agent:latest",
                "repo_dir": "eval-repo",
                "setup_commands": ["python -m pip install -e ."],
                "test_commands": ["pytest tests"],
                "apply_hidden_patches": ["tests"],
                "test_group_names": ["fail_to_pass", "pass_to_pass"],
                "test_command_template": "pytest {tests}",
                "timeout": 45,
            },
        },
    )

    config = parse_run_config(data)
    runner = config.build_runner()

    assert isinstance(runner, GitHubPatchRunner)
    assert runner.image == "securebench-agent:latest"
    assert runner.repo_dir == "eval-repo"
    assert runner.setup_commands == ("python -m pip install -e .",)
    assert runner.test_commands == ("pytest tests",)
    assert runner.apply_hidden_patches == ("tests",)
    assert runner.test_group_names == ("fail_to_pass", "pass_to_pass")
    assert runner.test_command_template == "pytest {tests}"
    assert runner.timeout == 45
    assert runner.sandbox_kwargs["network"] == "none"


def test_load_run_config_reads_yaml_file():
    config = load_run_config("configs/mmlu-static-smoke.yaml")

    assert config.run.id == "mmlu-static-smoke"
    assert config.dataset.name == MMLU_DATASET_ID
    assert config.producer.type == "static"


def test_load_openai_smoke_config_reads_yaml_file():
    config = load_run_config("configs/mmlu-openai-smoke.yaml")

    assert config.run.id == "mmlu-openai-smoke"
    assert config.producer.type == "openai_compatible"


def test_load_humaneval_static_smoke_config_reads_yaml_file():
    config = load_run_config("configs/humaneval-static-smoke.yaml")

    assert config.run.id == "humaneval-static-smoke"
    assert config.dataset.name == HUMANEVAL_DATASET_ID
    assert config.dataset.config == "openai_humaneval"
    assert config.dataset.split == "test"
    assert config.adapter.id == "humaneval"
    assert config.producer.type == "static"
    assert config.runner.type == "code_generation"


def test_load_humaneval_openai_smoke_config_reads_yaml_file():
    config = load_run_config("configs/humaneval-openai-smoke.yaml")

    assert config.run.id == "humaneval-openai-smoke"
    assert config.dataset.name == HUMANEVAL_DATASET_ID
    assert config.dataset.config == "openai_humaneval"
    assert config.producer.type == "openai_compatible"
    assert config.runner.type == "code_generation"


def test_load_swebench_verified_agent_smoke_config_reads_yaml_file():
    config = load_run_config("configs/swebench-verified-agent-smoke.yaml")

    assert config.run.id == "swebench-verified-agent-smoke"
    assert config.dataset.name == SWEBENCH_VERIFIED_DATASET_ID
    assert config.adapter.id == "swebench_verified"
    assert config.producer.type == "workspace_agent_patch"
    assert config.runner.type == "github_patch"
    assert config.sandbox.agent_workspace.network == "bridge"
    assert config.sandbox.test_sandbox.network == "none"
    producer = config.build_producer()
    assert isinstance(producer, WorkspaceAgentPatchProducer)
    assert producer.setup_commands[0] == "python -m pip install --upgrade pip 'setuptools<58' wheel"
    runner = config.build_runner()
    assert isinstance(runner, GitHubPatchRunner)
    assert runner.apply_hidden_patches == ("tests",)
    assert runner.test_group_names == ("fail_to_pass", "pass_to_pass")


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        ("schema_version", "9.9", "Unsupported schema_version"),
        ("dataset", {"provider": "local", "name": "cais/mmlu", "config": "x", "split": "test"}, "dataset.provider"),
        ("adapter", {"id": "missing"}, "Unknown benchmark adapter"),
        ("runner", {"type": "code_generation"}, "runner.type must match adapter task_type 'multiple_choice'"),
    ],
)
def test_parse_run_config_rejects_invalid_values(path, value, message):
    data = valid_config()
    data[path] = value

    with pytest.raises(ConfigError, match=message):
        parse_run_config(data)


def test_parse_run_config_rejects_non_positive_limit():
    data = valid_config()
    data["run"]["limit"] = 0

    with pytest.raises(ConfigError, match="run.limit"):
        parse_run_config(data)


def test_workspace_agent_patch_producer_rejects_invalid_command_lists():
    data = valid_config(
        dataset={
            "provider": "huggingface",
            "name": SWEBENCH_VERIFIED_DATASET_ID,
            "split": "test",
            "streaming": True,
        },
        adapter={"id": "swebench_verified"},
        producer={
            "type": "workspace_agent_patch",
            "config": {
                "model": "test-model",
                "allow_commands": "pytest",
            },
        },
        runner={"type": "github_patch"},
    )

    config = parse_run_config(data)
    with pytest.raises(ConfigError, match="allow_commands"):
        config.build_producer()


def test_workspace_agent_patch_producer_requires_model_or_replay_file():
    data = valid_config(
        dataset={
            "provider": "huggingface",
            "name": SWEBENCH_VERIFIED_DATASET_ID,
            "split": "test",
            "streaming": True,
        },
        adapter={"id": "swebench_verified"},
        producer={
            "type": "workspace_agent_patch",
            "config": {},
        },
        runner={"type": "github_patch"},
    )

    config = parse_run_config(data)
    with pytest.raises(ConfigError, match="model or replay_file"):
        config.build_producer()


def test_github_patch_runner_config_rejects_invalid_command_lists():
    data = valid_config(
        dataset={
            "provider": "huggingface",
            "name": SWEBENCH_VERIFIED_DATASET_ID,
            "split": "test",
            "streaming": True,
        },
        adapter={"id": "swebench_verified"},
        producer={
            "type": "workspace_agent_patch",
            "config": {
                "replay_file": "/workspace/replay.json",
            },
        },
        runner={
            "type": "github_patch",
            "config": {
                "test_group_names": "fail_to_pass",
            },
        },
    )

    config = parse_run_config(data)
    with pytest.raises(ConfigError, match="runner.config.test_group_names"):
        config.build_runner()


def test_parse_run_config_rejects_non_object_runner_config():
    data = valid_config(runner={"type": "multiple_choice", "config": "bad"})

    with pytest.raises(ConfigError, match="runner.config"):
        parse_run_config(data)


def test_parse_run_config_allows_non_mmlu_huggingface_dataset_name():
    data = valid_config()
    data["dataset"]["name"] = "example/custom-multiple-choice"

    config = parse_run_config(data)

    assert config.dataset.name == "example/custom-multiple-choice"


def test_parse_run_config_uses_adapter_task_type_for_runner_compatibility():
    data = valid_config()
    data["adapter"] = {"id": "humaneval"}
    data["runner"] = {"type": "code_generation"}

    config = parse_run_config(data)

    assert config.adapter.id == "humaneval"
    assert isinstance(config.build_runner(), CodeGenerationRunner)


def test_parse_run_config_applies_sandbox_policy_defaults_and_role_overrides():
    data = valid_config(
        sandbox={
            "defaults": {
                "network": "none",
                "cap_drop": ["ALL"],
                "read_only": True,
                "tmpfs": ["/tmp:size=64m"],
                "mem_limit": "512m",
                "pids_limit": 128,
                "security_opt": ["no-new-privileges:true"],
            },
            "agent_workspace": {
                "network": "bridge",
                "read_only": False,
            },
        }
    )

    config = parse_run_config(data)

    assert config.sandbox.defaults.mem_limit == "512m"
    assert config.sandbox.agent_workspace.network == "bridge"
    assert config.sandbox.agent_workspace.read_only is False
    assert config.sandbox.agent_workspace.mem_limit == "512m"
    assert config.sandbox.test_sandbox.network == "none"
    assert config.sandbox.test_sandbox.tmpfs == ("/tmp:size=64m",)


@pytest.mark.parametrize(
    ("sandbox", "message"),
    [
        ([], "sandbox must be an object"),
        ({"defaults": {"network": "open"}}, "sandbox.defaults.network"),
        ({"defaults": {"cap_drop": "ALL"}}, "sandbox.defaults.cap_drop"),
        ({"defaults": {"tmpfs": ["/tmp", ""]}}, "sandbox.defaults.tmpfs"),
        ({"defaults": {"security_opt": "no-new-privileges:true"}}, "sandbox.defaults.security_opt"),
        ({"defaults": {"mem_limit": 1}}, "sandbox.defaults.mem_limit"),
        ({"defaults": {"pids_limit": 0}}, "sandbox.defaults.pids_limit"),
    ],
)
def test_parse_run_config_rejects_invalid_sandbox_policy(sandbox, message):
    data = valid_config(sandbox=sandbox)

    with pytest.raises(ConfigError, match=message):
        parse_run_config(data)


def test_parse_run_config_supports_github_patch_runner_type():
    data = valid_config()
    data["adapter"] = {"id": "swebench_verified"}
    data["runner"] = {"type": "github_patch"}

    config = parse_run_config(data)

    assert config.adapter.id == "swebench_verified"
    assert isinstance(config.build_runner(), GitHubPatchRunner)
