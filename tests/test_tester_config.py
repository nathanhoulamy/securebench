from pathlib import Path

import pytest

from securebench.errors import ConfigError
from securebench.tester_config import load_tester_config, parse_tester_config


def valid_tester_config(**overrides):
    data = {
        "schema_version": "1.0",
        "run": {"id": "v2-run", "output_dir": "runs/v2-run"},
        "benchmark": {"manifest": "manifest-v2.yaml", "tasks": "tasks-v2.jsonl"},
        "harness": {"type": "codex", "env": ["OPENAI_API_KEY"]},
    }
    data.update(overrides)
    return data


def test_parse_tester_config_keeps_execution_choices_outside_rows():
    config = parse_tester_config(
        valid_tester_config(
            run={"id": "v2-run", "output_dir": "runs/v2-run", "max_workers": 4},
            docker={"max_cached_images": 2},
        )
    )

    assert config.schema_version == "1.0"
    assert config.run.max_workers == 4
    assert config.harness.type == "codex"
    assert config.harness.env == ("OPENAI_API_KEY",)
    assert config.docker.max_cached_images == 2
    assert not hasattr(config, "verification")


def test_load_tester_config_resolves_relative_paths(tmp_path):
    path = tmp_path / "configs" / "tester.yaml"
    path.parent.mkdir()
    path.write_text(
        """
schema_version: "1.0"
run:
  id: v2-run
  output_dir: runs/v2-run
benchmark:
  manifest: ../pack/manifest-v2.yaml
  tasks: ../pack/tasks-v2.jsonl
harness:
  type: command
  config:
    command: produce
"""
    )

    config = load_tester_config(path)

    assert config.run.output_dir == path.parent / "runs/v2-run"
    assert config.benchmark.manifest == path.parent / "../pack/manifest-v2.yaml"
    assert config.harness.config == {"command": "produce"}


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"schema_version": "0.2"}, "Unsupported tester schema_version"),
        ({"verification": {}}, "root contains unsupported field"),
        ({"run": "bad"}, "root.run must be an object"),
        ({"benchmark": "bad"}, "root.benchmark must be an object"),
        ({"harness": "bad"}, "root.harness must be an object"),
        ({"docker": {"max_cached_images": 0}}, "must be a positive integer"),
        (
            {"run": {"id": "x", "output_dir": "runs/x", "max_workers": True}},
            "must be a positive integer",
        ),
        ({"harness": {"type": "unknown"}}, "harness.type must be one of"),
        ({"harness": {"type": "codex", "env": ["BAD=value"]}}, "without '='"),
    ],
)
def test_tester_config_rejects_invalid_shape(override, match):
    with pytest.raises(ConfigError, match=match):
        parse_tester_config(valid_tester_config(**override))
