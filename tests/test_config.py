from types import SimpleNamespace

import pytest

from securebench.candidates import StaticCandidateProducer, TextCompletionProducer, WorkspaceAgentPatchProducer
from securebench.config import ConfigError, load_run_config, parse_run_config
from securebench.datasets import HUMANEVAL_DATASET_ID, MMLU_DATASET_ID, SWEBENCH_VERIFIED_DATASET_ID
from securebench.runners import CodeCompletionRunner, GitHubPatchRunner, MultipleChoiceRunner


@pytest.fixture(autouse=True)
def fake_environment_image_build(monkeypatch):
    seen = {"commands": []}

    def fake_run(command, **kwargs):
        seen["commands"].append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(returncode=0, stdout="[]", stderr="")
        if command[:2] == ["docker", "build"]:
            return SimpleNamespace(returncode=0, stdout="built", stderr="")
        raise AssertionError(f"unexpected subprocess command: {command}")

    monkeypatch.setattr("securebench.environment.subprocess.run", fake_run)
    return seen


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
    assert config.environment.python == "3.11-slim"
    assert config.environment.image == "securebench-agent-runtime:py3.11-slim"


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
                "allow_commands": ["git", "pytest"],
                "deny_commands": ["curl"],
            },
        },
        environment={
            "python": "3.9-slim",
            "setup": ["python -m pip install pytest"],
            "network": "bridge",
            "writable": True,
        },
        runner={"type": "github_patch"},
    )

    config = parse_run_config(data)
    producer = config.build_producer()

    assert isinstance(producer, WorkspaceAgentPatchProducer)
    assert config.producer.type == "workspace_agent_patch"
    sandbox = producer.sandbox_factory()
    assert sandbox.env_names == ("TEST_API_KEY",)
    assert sandbox.image == "securebench-agent-runtime:py3.9-slim"
    assert sandbox.network == "bridge"
    assert sandbox.cap_drop == ("ALL",)
    assert sandbox.read_only is False
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
                "repo_dir": "eval-repo",
                "test_commands": ["pytest tests"],
                "apply_hidden_patches": ["tests"],
                "test_group_names": ["fail_to_pass", "pass_to_pass"],
                "test_command_template": "pytest {tests}",
                "timeout": 45,
            },
        },
        environment={
            "setup": ["python -m pip install wheel"],
            "runner": {
                "setup": ["python -m pip install -e ."],
                "network": "bridge",
                "writable": True,
            },
        },
    )

    config = parse_run_config(data)
    runner = config.build_runner()

    assert isinstance(runner, GitHubPatchRunner)
    assert runner.image == "securebench-agent-runtime:py3.11-slim"
    assert runner.repo_dir == "eval-repo"
    assert runner.setup_commands == ("python -m pip install wheel", "python -m pip install -e .")
    assert runner.test_commands == ("pytest tests",)
    assert runner.apply_hidden_patches == ("tests",)
    assert runner.test_group_names == ("fail_to_pass", "pass_to_pass")
    assert runner.test_command_template == "pytest {tests}"
    assert runner.timeout == 45
    assert runner.sandbox_kwargs["network"] == "bridge"
    assert runner.sandbox_kwargs["read_only"] is False


def test_environment_role_overrides_shared_defaults():
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
                "test_commands": ["pytest tests"],
            },
        },
        environment={
            "python": "3.10-slim",
            "packages": ["gfortran", "libhdf5-dev"],
            "network": "bridge",
            "writable": True,
            "setup": ["python -m pip install base"],
            "producer": {
                "setup": ["python -m pip install agent-tools"],
            },
            "runner": {
                "network": "none",
                "writable": False,
                "setup": ["python -m pip install test-tools"],
            },
        },
    )

    config = parse_run_config(data)
    producer = config.build_producer()
    runner = config.build_runner()

    producer_sandbox = producer.sandbox_factory()
    assert producer_sandbox.image.startswith("securebench-agent-runtime:py3.10-slim-")
    assert producer_sandbox.network == "bridge"
    assert producer_sandbox.read_only is False
    producer_sandbox.close()
    assert producer.setup_commands == (
        "python -m pip install base",
        "python -m pip install agent-tools",
    )
    assert runner.image == producer_sandbox.image
    assert runner.sandbox_kwargs["network"] == "none"
    assert runner.sandbox_kwargs["read_only"] is True
    assert runner.setup_commands == (
        "python -m pip install base",
        "python -m pip install test-tools",
    )


@pytest.mark.parametrize(
    ("component", "config", "message"),
    [
        ("producer", {"image": "securebench-agent:latest", "model": "test-model"}, "producer.config.image"),
        (
            "producer",
            {"setup_commands": ["python -m pip install pytest"], "model": "test-model"},
            "producer.config.setup_commands",
        ),
        ("runner", {"image": "securebench-agent:latest"}, "runner.config.image"),
        ("runner", {"setup_commands": ["python -m pip install pytest"]}, "runner.config.setup_commands"),
    ],
)
def test_parse_run_config_rejects_legacy_environment_fields(component, config, message):
    data = valid_config(
        dataset={
            "provider": "huggingface",
            "name": SWEBENCH_VERIFIED_DATASET_ID,
            "split": "test",
            "streaming": True,
        },
        adapter={"id": "swebench_verified"},
        producer={"type": "workspace_agent_patch", "config": {"model": "test-model"}},
        runner={"type": "github_patch", "config": {}},
    )
    data[component]["config"].update(config)

    with pytest.raises(ConfigError, match=message):
        parse_run_config(data)


def test_environment_missing_image_triggers_docker_build(monkeypatch):
    seen = []

    def fake_run(command, **kwargs):
        seen.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="missing")
        if command[:2] == ["docker", "build"]:
            return SimpleNamespace(returncode=0, stdout="built", stderr="")
        raise AssertionError(f"unexpected subprocess command: {command}")

    monkeypatch.setattr("securebench.environment.subprocess.run", fake_run)
    data = valid_config(
        dataset={
            "provider": "huggingface",
            "name": SWEBENCH_VERIFIED_DATASET_ID,
            "split": "test",
            "streaming": True,
        },
        adapter={"id": "swebench_verified"},
        producer={"type": "workspace_agent_patch", "config": {"replay_file": "/workspace/replay.json"}},
        runner={"type": "github_patch"},
        environment={"python": "3.9-slim", "packages": ["gfortran", "libxml2-dev"]},
    )

    parse_run_config(data).build_producer()

    assert seen[0][0:3] == ["docker", "image", "inspect"]
    assert seen[0][3].startswith("securebench-agent-runtime:py3.9-slim-")
    assert seen[1][:2] == ["docker", "build"]
    assert "--build-arg" in seen[1]
    assert "PYTHON_VERSION=3.9-slim" in seen[1]
    assert "ENVIRONMENT_PACKAGES=gfortran libxml2-dev" in seen[1]
    assert "-t" in seen[1]
    assert seen[0][3] in seen[1]


def test_environment_package_order_does_not_change_image_tag():
    first = parse_run_config(valid_config(environment={"python": "3.9-slim", "packages": ["zlib1g-dev", "gfortran"]}))
    second = parse_run_config(valid_config(environment={"python": "3.9-slim", "packages": ["gfortran", "zlib1g-dev"]}))

    assert first.environment.image == second.environment.image
    assert first.environment.image.startswith("securebench-agent-runtime:py3.9-slim-")
    assert first.environment.packages == ("gfortran", "zlib1g-dev")


def test_environment_python_variant_uses_explicit_base_tag(monkeypatch):
    seen = []

    def fake_run(command, **kwargs):
        seen.append(command)
        if command[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="missing")
        if command[:2] == ["docker", "build"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected subprocess command: {command}")

    monkeypatch.setattr("securebench.environment.subprocess.run", fake_run)
    data = valid_config(
        dataset={
            "provider": "huggingface",
            "name": SWEBENCH_VERIFIED_DATASET_ID,
            "split": "test",
            "streaming": True,
        },
        adapter={"id": "swebench_verified"},
        producer={"type": "workspace_agent_patch", "config": {"replay_file": "/workspace/replay.json"}},
        runner={"type": "github_patch"},
        environment={"python": "3.9-slim-bullseye"},
    )

    parse_run_config(data).build_producer()

    assert "PYTHON_VERSION=3.9-slim-bullseye" in seen[1]


def test_environment_packages_are_deduplicated_before_build():
    config = parse_run_config(
        valid_config(environment={"python": "3.9-slim", "packages": ["gfortran", "gfortran"]})
    )

    assert config.environment.packages == ("gfortran",)


def test_environment_docker_build_failure_is_config_error(monkeypatch):
    def fake_run(command, **kwargs):
        if command[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="missing")
        if command[:2] == ["docker", "build"]:
            return SimpleNamespace(returncode=42, stdout="", stderr="build failed")
        raise AssertionError(f"unexpected subprocess command: {command}")

    monkeypatch.setattr("securebench.environment.subprocess.run", fake_run)
    data = valid_config(
        dataset={
            "provider": "huggingface",
            "name": SWEBENCH_VERIFIED_DATASET_ID,
            "split": "test",
            "streaming": True,
        },
        adapter={"id": "swebench_verified"},
        producer={"type": "workspace_agent_patch", "config": {"replay_file": "/workspace/replay.json"}},
        runner={"type": "github_patch"},
        environment={"python": "3.9-slim"},
    )

    with pytest.raises(ConfigError, match="Failed to build environment image"):
        parse_run_config(data).build_producer()


def test_agent_dockerfile_declares_python_version_build_arg():
    dockerfile = open("docker/agent.Dockerfile").read()
    assert "ARG PYTHON_VERSION=3.11-slim" in dockerfile
    assert "FROM python:${PYTHON_VERSION}" in dockerfile
    assert 'ARG ENVIRONMENT_PACKAGES=""' in dockerfile
    assert "${ENVIRONMENT_PACKAGES}" in dockerfile
    assert "ENV PYTHONPATH=/opt/securebench-agent" in dockerfile
    assert "COPY securebench_agent ./securebench_agent" in dockerfile
    assert "COPY securebench ./securebench" not in dockerfile
    assert 'CMD ["python", "-m", "securebench_agent.run", "--help"]' in dockerfile
    assert "python -m pip install ." not in dockerfile


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
    assert config.runner.type == "code_completion"


def test_load_humaneval_openai_smoke_config_reads_yaml_file():
    config = load_run_config("configs/humaneval-openai-smoke.yaml")

    assert config.run.id == "humaneval-openai-smoke"
    assert config.dataset.name == HUMANEVAL_DATASET_ID
    assert config.dataset.config == "openai_humaneval"
    assert config.producer.type == "openai_compatible"
    assert config.runner.type == "code_completion"


def test_load_swebench_verified_agent_smoke_config_reads_yaml_file():
    config = load_run_config("configs/swebench-verified-agent-smoke.yaml")

    assert config.run.id == "swebench-verified-agent-smoke"
    assert config.dataset.name == SWEBENCH_VERIFIED_DATASET_ID
    assert config.adapter.id == "swebench_verified"
    assert config.producer.type == "workspace_agent_patch"
    assert config.runner.type == "github_patch"
    assert config.environment.network == "bridge"
    assert config.environment.writable is True
    producer = config.build_producer()
    assert isinstance(producer, WorkspaceAgentPatchProducer)
    assert config.environment.python == "3.9-slim-bullseye"
    assert producer.setup_commands[0] == "python -m pip install --upgrade 'pip<24' 'setuptools<58' wheel"
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
        ("runner", {"type": "code_completion"}, "runner.type must match adapter task_type 'multiple_choice'"),
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
    data["runner"] = {"type": "code_completion"}

    config = parse_run_config(data)

    assert config.adapter.id == "humaneval"
    assert isinstance(config.build_runner(), CodeCompletionRunner)


def test_parse_run_config_rejects_removed_sandbox_policy():
    data = valid_config(sandbox={"defaults": {"network": "bridge"}})

    with pytest.raises(ConfigError, match="sandbox is no longer supported"):
        parse_run_config(data)


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ([], "environment must be an object"),
        ({"python": ""}, "environment.python"),
        ({"python": "3/11"}, "environment.python"),
        ({"packages": "gfortran"}, "environment.packages"),
        ({"packages": ["gfortran", "bad package"]}, "environment.packages"),
        ({"packages": ["gfortran", "$(bad)"]}, "environment.packages"),
        ({"network": "open"}, "environment.network"),
        ({"writable": "yes"}, "environment.writable"),
        ({"setup": ["python -m pip install pytest", ""]}, "environment.setup"),
        ({"producer": []}, "environment.producer"),
        ({"runner": {"network": "open"}}, "environment.runner.network"),
        ({"runner": {"writable": "yes"}}, "environment.runner.writable"),
    ],
)
def test_parse_run_config_rejects_invalid_environment(environment, message):
    data = valid_config(environment=environment)

    with pytest.raises(ConfigError, match=message):
        parse_run_config(data)


def test_parse_run_config_supports_github_patch_runner_type():
    data = valid_config()
    data["adapter"] = {"id": "swebench_verified"}
    data["runner"] = {"type": "github_patch"}

    config = parse_run_config(data)

    assert config.adapter.id == "swebench_verified"
    assert isinstance(config.build_runner(), GitHubPatchRunner)
