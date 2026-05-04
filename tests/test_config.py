import pytest

from securebench.candidates import StaticCandidateProducer, TextCompletionProducer
from securebench.config import ConfigError, load_run_config, parse_run_config
from securebench.datasets import MMLU_DATASET_ID
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
            "kind": "static",
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


def test_parse_run_config_builds_openai_compatible_producer():
    data = valid_config(
        producer={
            "kind": "openai_compatible",
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


def test_load_run_config_reads_yaml_file():
    config = load_run_config("configs/mmlu-static-smoke.yaml")

    assert config.run.id == "mmlu-static-smoke"
    assert config.dataset.name == MMLU_DATASET_ID
    assert config.producer.kind == "static"


def test_load_openai_smoke_config_reads_yaml_file():
    config = load_run_config("configs/mmlu-openai-smoke.yaml")

    assert config.run.id == "mmlu-openai-smoke"
    assert config.producer.kind == "openai_compatible"


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


def test_parse_run_config_supports_github_patch_runner_type():
    data = valid_config()
    data["adapter"] = {"id": "swebench_verified"}
    data["runner"] = {"type": "github_patch"}

    config = parse_run_config(data)

    assert config.adapter.id == "swebench_verified"
    assert isinstance(config.build_runner(), GitHubPatchRunner)
